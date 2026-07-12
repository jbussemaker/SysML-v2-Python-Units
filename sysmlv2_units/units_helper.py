import math
import syside
import logging
from collections import OrderedDict
from typing import Tuple, Optional, Union, Dict, List, Type
from pint import Unit, Quantity, get_application_registry, UndefinedUnitError, register_unit_format

__all__ = ['SysMLUnitsHelper', 'ureg', 'Unit', 'Quantity', 'UndefinedUnitError']

log = logging.getLogger('sysml.units')

ureg = get_application_registry()
_UNKNOWN_UNIT = object()


class SysMLUnitsHelper:
    """
    Class with functions for dealing with units and quantities (value + units) in SysML v2.
    On the Python-side, it uses the [pint](https://pint.readthedocs.io/) package.

    Supports units from the SysML units library and units expressions (e.g. defining your own units by combining
    existing units through operations like division, multiplication, exponentiation, etc.).

    Raises an `UndefinedUnitError` if any unit parsing or conversion to/from SysML fails.
    """

    dimensionless_units_pint = ureg.dimensionless
    dimensionless_units_sysml_key = 'MeasurementReferences::one'

    _binary_operators = {
        syside.Operator.Divide: '/',
        syside.Operator.Multiply: '*',
        syside.Operator.ExponentStar: '**',
        syside.Operator.ExponentCaret: '^',
    }

    _sysml_alias_map: Dict[str, List[str]] = {}  # units attr key --> list of alias names
    _sysml_units_map: Dict[str, str] = {}  # alias name --> units attr key

    _pint_sysml_units_map = {}
    _sysml_pint_units_map = {}

    _sysml_quantities_units_map: Dict[str, str] = {}  # quantity attr key --> units attr key

    _do_log = True

    def __init__(self, model: syside.Model):
        doc_namespace_map = {}

        self.unit_base_def = self._get_element_by_qualified_name(model, doc_namespace_map,
            'MeasurementReferences::MeasurementUnit', syside.AttributeDefinition, env=True)
        self.scale_base_def = self._get_element_by_qualified_name(model, doc_namespace_map,
            'MeasurementReferences::MeasurementScale', syside.AttributeDefinition, env=True)

        self.quantity_value_base_def = self._get_element_by_qualified_name(model, doc_namespace_map,
            'Quantities::TensorQuantityValue', syside.AttributeDefinition, env=True)

        self.dimensionless_units_def_sysml = self._get_element_by_qualified_name(model, doc_namespace_map,
            'MeasurementReferences::DimensionOneUnit', syside.AttributeDefinition, env=True)
        self.dimensionless_units_sysml = self._get_element_by_qualified_name(model, doc_namespace_map,
            'MeasurementReferences::one', syside.AttributeUsage, env=True)
        self.__class__.dimensionless_units_sysml_key = self._sysml_attr_key(self.dimensionless_units_sysml)

        self.units_libraries = [
            self._search_namespace(model, doc_namespace_map, 'SI', env=True),
            self._search_namespace(model, doc_namespace_map, 'USCustomaryUnits', env=True),
        ]
        sysml_alias_map, sysml_units_map, self._sysml_obj_map = self._get_sysml_units_map()
        self._init_mappings(sysml_units_map, sysml_alias_map)

        if len(self.__class__._sysml_quantities_units_map) == 0:
            isq = self._get_element_by_qualified_name(
                model, doc_namespace_map, 'ISQBase::isq', syside.AttributeUsage, env=True)
            si = self._get_element_by_qualified_name(
                model, doc_namespace_map, 'SI::si', syside.AttributeUsage, env=True)

            dimensionless_quantities = [
                self._get_element_by_qualified_name(model, doc_namespace_map,
                    'MeasurementReferences::DimensionOneValue', syside.AttributeDefinition, env=True),
                self.dimensionless_units_def_sysml,
            ]

            self.__class__._sysml_quantities_units_map = self._map_base_quantities(isq, si, dimensionless_quantities)

        if any([prop is None for prop in [
            self.unit_base_def,
            self.scale_base_def,
            self.dimensionless_units_sysml,
        ]+self.units_libraries]):
            raise RuntimeError('Not all units helper elements found!')

    ###################################################################
    ### SysML to Python (pint) conversion functions (SysML getters) ###
    ###################################################################

    def get_quantity(self, feature: Union[syside.Feature, syside.Expression], raise_if_unknown_unit=True) -> Quantity:
        """
        Parses a feature value and returns a quantity (value + units).
        Raises a ValueError if the value is not numerical.
        """

        # Get units if set
        value_expression, is_negation, units, _ = self._get_feature_value_units(
            feature, raise_if_unknown_unit=raise_if_unknown_unit)

        # Get the value
        if value_expression is None:
            raise ValueError(f'No feature value set on feature: {feature}')

        value = self._simple_parse_value(value_expression)

        if is_negation:
            value = -value

        return self.quantity(value, units)

    def get_units(self, feature: Union[syside.Feature, syside.Expression], raise_if_unknown_unit=True) \
            -> Tuple[Optional[Unit], Optional[syside.AttributeUsage]]:
        """
        Converts a unit-reference feature value to a Python/pint unit.
        Also returns the original units attribute that was set (if applicable).
        """

        # Check if the feature has a value
        if (isinstance(feature, syside.Feature) and not isinstance(feature, syside.Expression)
                and feature.feature_value is None):

            # If not, check if the feature itself is a unit
            if isinstance(feature, syside.AttributeUsage):
                if feature == self.dimensionless_units_sysml:
                    return None, None

                # Check if the feature derives from a QuantityValue
                if self.is_typed_by_quantity_value(feature):
                    preferred_units = self.get_quantity_value_units(feature, raise_if_unknown_unit=raise_if_unknown_unit)
                    return preferred_units, None

                # Directly try to parse the unit
                parsed_units, units_attr = self._parse_units_attr(feature, raise_if_unknown_unit=raise_if_unknown_unit)
                if parsed_units is not None:
                    return parsed_units, units_attr

            raise ValueError(f'No feature value set on feature: {feature}')

        _, _, units, units_attr = self._get_feature_value_units(feature, raise_if_unknown_unit=raise_if_unknown_unit)
        return units, units_attr

    def _get_feature_value_units(self, feature: Union[syside.Feature, syside.Expression], raise_if_unknown_unit=True) \
            -> Tuple[Optional[syside.Expression], bool, Optional[Unit], Optional[syside.AttributeUsage]]:
        """
        Parses a feature value and returns the (pint) units if set.
        Returns the (contained) feature that contains the value, so that should still be parsed.
        """

        if isinstance(feature, syside.Expression):
            value_expression = feature
        else:
            if feature.feature_value is None:
                return None, False, None, None

            value_expression: Optional[syside.Expression] = feature.feature_value.value

        # Check if it is a negation
        is_negation = False
        if (isinstance(value_expression, syside.OperatorExpression) and
                value_expression.operator == syside.Operator.Minus):

            value_feature = value_expression.children.elements[0]
            value_expression = value_feature.feature_value.value
            is_negation = True

        # Check if it is a quantity expression: <child1>[<child2>]
        if (isinstance(value_expression, syside.OperatorExpression)
                and value_expression.operator == syside.Operator.Quantity
                and len(value_expression.children) == 2):

            units_feature: syside.Feature
            value_feature, units_feature = value_expression.children.elements

            value_expression = value_feature.feature_value.value

            units, units_attr = self._parse_units_feature(units_feature, raise_if_unknown_unit=raise_if_unknown_unit)

        # Otherwise try to directly parse the value expression as units
        else:
            units, units_attr = self._parse_units_feature(value_expression, raise_if_unknown_unit=raise_if_unknown_unit)

            if units is not None and isinstance(units, Unit):
                value_expression = None
            else:
                units = units_attr = None

        return value_expression, is_negation, units, units_attr

    def _parse_units_feature(self, units_feature: Union[syside.Feature, syside.Expression],
                             raise_if_unknown_unit=True) \
            -> Tuple[Union[Optional[Unit], int], Optional[syside.AttributeUsage]]:
        """
        Parses a feature that defines the units.
        Additionally, returns the units attribute that was set to define the unit if applicable.
        """

        if isinstance(units_feature, syside.Expression):
            units_expression = units_feature
        else:
            units_expression = units_feature.feature_value.value

        # Parse a referenced units attribute, e.g.: SI::m
        if isinstance(units_expression, syside.FeatureReferenceExpression):
            # Convert to pint units
            units_attr = units_expression.referent
            if not isinstance(units_attr, syside.AttributeUsage):
                return None, None

            # Parse the units attr
            units, _ = self._parse_units_attr(units_attr, raise_if_unknown_unit=raise_if_unknown_unit)
            return units, units_attr

        # Parse an exponential (as part of parsing a units expression)
        if (isinstance(units_expression, syside.LiteralInteger) or
                (isinstance(units_expression, syside.OperatorExpression)
                 and units_expression.operator == syside.Operator.Minus)):

            value = self._simple_parse_value(units_expression)
            return value, None

        # Recursively parse a units expression, e.g.: m*s^-1
        if (isinstance(units_expression, syside.OperatorExpression) and
                units_expression.operator in self._binary_operators and len(units_expression.children) == 2):

            left_side_feature, right_side_feature = units_expression.children.elements
            operator_str = self._binary_operators[units_expression.operator]

            left_side_units, _ = self._parse_units_feature(
                left_side_feature, raise_if_unknown_unit=raise_if_unknown_unit)
            right_side_units, _ = self._parse_units_feature(
                right_side_feature, raise_if_unknown_unit=raise_if_unknown_unit)

            # Check for unknown or dimensionless units
            if right_side_units is None:
                return left_side_units, None

            if left_side_units is None:
                left_side_units = self.dimensionless_units_pint

            # Parse python units
            left_str = f'{left_side_units:~C}' if isinstance(left_side_units, Unit) else str(left_side_units)
            right_str = f'{right_side_units:~C}' if isinstance(right_side_units, Unit) else str(right_side_units)
            units = self.parse_python_units(' '.join([left_str, operator_str, right_str]))
            return units, None

        return None, None

    def _parse_units_attr(self, units_attr: syside.AttributeUsage, raise_if_unknown_unit=True) \
            -> Tuple[Optional[Unit], Optional[syside.AttributeUsage]]:
        """Parse a referred-to attribute, also trying chaining via value or subsetting."""

        # Parse the units attr
        try:
            units = self.get_python_units(units_attr, raise_if_unknown_unit=True, cache_unknown=False)
            return units, units_attr

        except UndefinedUnitError:

            # Try to parse a unit set as the value
            if units_attr.feature_value is not None:
                parsed_units, value_units_attr = self._parse_units_feature(
                    units_attr.feature_value.value, raise_if_unknown_unit=False)
                if parsed_units is not None:
                    return parsed_units, value_units_attr

            # Try to parse a unit by subsetting
            for specialization, subset_el in units_attr.heritage:
                if isinstance(specialization, syside.Subsetting) and isinstance(subset_el, syside.AttributeUsage):
                    parsed_units, _ = self._parse_units_attr(subset_el, raise_if_unknown_unit=False)
                    if parsed_units is not None:
                        return parsed_units, subset_el

            if raise_if_unknown_unit:
                raise
            return None, None

    @classmethod
    def _simple_parse_value(cls, expression: syside.Expression):
        """Parses int, real, inf, null (NaN) values, positive or negative."""

        # Parse a list
        if isinstance(expression, syside.OperatorExpression) and expression.operator == syside.Operator.Comma:
            values = []
            for child_feature in expression.children.elements:
                if child_feature.feature_value and child_feature.feature_value.value:
                    child_value = child_feature.feature_value.value
                    values.append(cls._simple_parse_value(child_value))
            return values

        # Feature chain
        if isinstance(expression, syside.FeatureChainExpression):
            return expression.target_feature.feature_target

        # Feature reference
        if isinstance(expression, syside.FeatureReferenceExpression):
            return expression.referent

        # Check if it is a negation
        is_negation = False
        if isinstance(expression, syside.OperatorExpression) and expression.operator == syside.Operator.Minus:

            value_feature = expression.children.elements[0]
            expression = value_feature.feature_value.value
            is_negation = True

        # Parse numerical values
        if isinstance(expression, (syside.LiteralInteger, syside.LiteralRational)):
            value = expression.value
            return -value if is_negation else value

        # Parse infinity and null
        if isinstance(expression, syside.NullExpression):
            return math.nan
        if isinstance(expression, syside.LiteralInfinity):
            return -math.inf if is_negation else math.inf

        raise ValueError(f'Could not parse simple expression: {expression}')

    ################################
    ### SysML printing functions ###
    ################################

    @classmethod
    def to_text(cls, element: syside.Element, printer_config: syside.PrinterConfig = None):
        """
        Render an element as SysML v2 textual notation, using the units ReferencePrinter so that units are printed
        using their short names.

        Note: this only works if a UnitsHelper has been instantiated at least once (to initialize the caches).
        """

        # Get printer config
        if printer_config is None:
            printer_config = syside.PrinterConfig(line_width=120, tab_width=4)

        # Get the reference printer
        reference_printer = cls.get_reference_printer()

        # Create the printer and print the model
        printer = syside.ModelPrinter.sysml(reference_printer=reference_printer)
        sysml_text = syside.pprint(element, printer, printer_config)

        return sysml_text

    @classmethod
    def get_reference_printer(cls) -> syside.ReferencePrinter:
        """Returns a reference printer that prints references to units using their short name."""
        alias_map = cls._sysml_alias_map

        def get_name_pref(target: syside.Element, referent: syside.Element) -> syside.NamePreference:
            # Check if the target is a unit
            if target.__class__ == syside.AttributeUsage:
                units_attr_key = cls._sysml_attr_key(target)
                if units_attr_key in alias_map:
                    return syside.NamePreference.Shortest

            return syside.NamePreference.Regular

        return syside.ReferencePrinter(get_name_pref)

    #######################################################################
    ### Python (pint/str) to SysML conversion functions (SysML setters) ###
    #######################################################################

    def set_quantity(self, feature: syside.Feature, quantity: Quantity, raise_if_unknown_unit=True):
        """Set the feature value to a quantity (value + units)."""
        self.set_value_and_units(feature, quantity.magnitude, quantity.units,
                                 raise_if_unknown_unit=raise_if_unknown_unit)

    def set_value_and_units(self, feature: syside.Feature, value: float,
                            units: Union[Unit, str, syside.AttributeUsage] = None, raise_if_unknown_unit=True):
        """Same as set_quantity, but by supplying the value and units separately, also supports SysML units."""

        # Set minus operator if needed
        if value < 0:
            feature = self._set_minus_operator(feature)
            value = -value

        # Set units if needed
        value_feature = self._set_feature_value_units(
            feature, units, raise_if_unknown_unit=raise_if_unknown_unit)

        # Set the value
        self._set_simple_value(value_feature, value)

    def set_units(self, feature: syside.Feature, units: Union[Unit, str, syside.AttributeUsage],
                  raise_if_unknown_unit=True):
        """Set the feature value to a unit."""

        # Parse units if needed
        if isinstance(units, str):
            units = self.parse_python_units(units, raise_if_unknown_unit=raise_if_unknown_unit)

        # Get the associated SysML units attribute
        if isinstance(units, syside.AttributeUsage):
            units_attr = units
        else:
            units_attr = self.get_sysml_units(units, raise_if_unknown_unit=raise_if_unknown_unit)

        # Create and set the reference expression
        reference_expression: syside.FeatureReferenceExpression
        _, reference_expression = feature.feature_value_member.set_member_element(
            syside.FeatureReferenceExpression)

        reference_expression.referent_member.set_member_element(units_attr)

    def _set_feature_value_units(self, feature: syside.Feature, units: Union[Unit, str, syside.AttributeUsage] = None,
                                raise_if_unknown_unit=True) -> syside.Feature:
        """
        Optionally create a new quantity expression if a unit should be set.
        Returns the feature that should get the actual value (not set yet).
        """

        # Parse units if needed
        if units and isinstance(units, syside.AttributeUsage):

            # Check if dimensionless
            if units == self.dimensionless_units_sysml:
                return feature

        else:
            units = self.parse_python_units(units, raise_if_unknown_unit=raise_if_unknown_unit)

            # Check if dimensionless
            if not units:
                return feature

        # Create a new Quantity expression
        quantity_expression: syside.OperatorExpression
        _, quantity_expression = feature.feature_value_member.set_member_element(syside.OperatorExpression)
        quantity_expression.operator = syside.ExplicitOperator.Quantity

        _, value_feature = quantity_expression.children.append(syside.ParameterMembership, syside.Feature)

        # Set the units
        units_feature: syside.Feature
        _, units_feature = quantity_expression.children.append(syside.ParameterMembership, syside.Feature)

        self.set_units(units_feature, units, raise_if_unknown_unit=raise_if_unknown_unit)

        return value_feature

    @staticmethod
    def _set_minus_operator(feature: syside.Feature) -> syside.Feature:

        expression: syside.OperatorExpression
        _, expression = feature.feature_value_member.set_member_element(syside.OperatorExpression)
        expression.operator = syside.ExplicitOperator.Minus

        _, value_feature = expression.children.append(syside.ParameterMembership, syside.Feature)
        return value_feature

    @classmethod
    def _set_simple_value(cls, feature: syside.Feature, value):
        """Sets positive or negative int, real, inf or null (NaN) values."""

        # Create minus operator if needed
        value_feature = feature
        if value < 0:
            value_feature = cls._set_minus_operator(value_feature)
            value = -value

        # Set actual value
        if math.isinf(value):
            value_feature.feature_value_member.set_member_element(syside.LiteralInfinity)

        elif value is None or math.isnan(value):
            value_feature.feature_value_member.set_member_element(syside.NullExpression)

        elif isinstance(value, int):
            _, literal = value_feature.feature_value_member.set_member_element(syside.LiteralInteger)
            literal.value = value

        elif isinstance(value, float):
            _, literal = value_feature.feature_value_member.set_member_element(syside.LiteralRational)
            literal.value = value

        else:
            raise ValueError(f'Could not set simple value: {value}')

    ###########################################
    ### Unit conversion / parsing functions ###
    ###########################################

    @classmethod
    def get_python_units(cls, units_attr: Union[syside.AttributeUsage, str], raise_if_unknown_unit=True, cache_unknown=True) \
            -> Optional[Unit]:
        """Convert a units attribute (SysML) to pint/Python units."""

        # Check if dimensionless
        units_attr_key = cls._sysml_attr_key(units_attr)
        if units_attr_key == cls.dimensionless_units_sysml_key:
            return

        # Check the cache
        pint_units = cls._get_cache_from_sysml(units_attr, raise_if_unknown_unit=raise_if_unknown_unit)
        if pint_units is not None:
            return pint_units

        # Try all aliases of the units attribute
        for alias in cls._sysml_alias_map.get(units_attr_key, []):
            pint_units = cls.parse_python_units(alias, raise_if_unknown_unit=False)
            if pint_units is not None:
                break

        # Expand the search by replacing special characters by more common ones
        if pint_units is None:
            for alias in cls._sysml_alias_map.get(units_attr_key, []):
                common_alias = (
                    alias
                    .replace('⋅', '*')
                    .replace('metre', 'meter')
                    .replace('litre', 'liter')
                )
                pint_units = cls.parse_python_units(common_alias, raise_if_unknown_unit=False)
                if pint_units is not None:
                    break

        # Check if the units were found
        units_attr_str = f'<{units_attr.short_name or ""}> {units_attr.name}' \
            if isinstance(units_attr, syside.AttributeUsage) else units_attr
        if pint_units is not None:
            if cls._do_log:
                log.debug(f'Converted SysML units "{units_attr_str}" to pint units "<{pint_units:~P}> {pint_units:P}"')

            cls._cache_units_map(pint_units, units_attr)
            return pint_units

        # No units were found
        if cls._do_log:
            log.debug(f'Could not convert SysML units "{units_attr_str}" to pint units')
        if cache_unknown:
            cls._cache_units_map(_UNKNOWN_UNIT, units_attr)

        # Raise an error if needed
        if raise_if_unknown_unit:
            raise UndefinedUnitError(units_attr_str)

    def get_sysml_units(self, units: Union[Unit, str] = None, raise_if_unknown_unit=True, cache_unknown=True) \
            -> Optional[syside.AttributeUsage]:
        """Gets SysML units for the give Python/pint units. Returns None for dimensionless."""

        units_str_try = []

        # Convert to a Unit object if needed
        if not isinstance(units, Unit):

            if isinstance(units, str):
                units_str_try.append(units)

            units = self.parse_python_units(units, raise_if_unknown_unit=raise_if_unknown_unit)

        # Check if dimensionless
        if units is None or units == self.dimensionless_units_pint:
            return

        assert isinstance(units, Unit)

        # Check the mapping cache
        units_attr = self._get_cache_from_pint(units, raise_if_unknown_unit=raise_if_unknown_unit)
        if units_attr is not None:
            return units_attr

        # Get string to search for by printing the units in various formats
        def _get_str_formats(u: Unit):
            formats = [
                str(u),
                str(u).replace('_', ' '),
                f'{u:C}',  # Compact
                f'{u:P}',  # Pretty-printed
                f'{u:~C}',  # Abbreviated, compact
                f'{u:~P}',  # Abbreviated, pretty-printed
                f'{u:S}',  # SysML-style: see function _print_sysml_like
            ]
            if 'meter' in formats[0] or 'liter' in formats[0]:
                formats += [fmt
                            .replace('meter', 'metre')
                            .replace('liter', 'litre')
                            for fmt in formats]
            return formats

        units_str_try += _get_str_formats(units)

        # Search for the associated SysML units
        unique_search_str = list(OrderedDict.fromkeys(units_str_try).keys())
        for search_str in unique_search_str:
            units_attr_key = self._sysml_units_map.get(search_str.strip())

            if units_attr_key is not None:
                units_attr = self._sysml_obj_map[units_attr_key]
                assert units_attr != self.dimensionless_units_sysml

                self._cache_units_map(units, units_attr)
                if self.__class__._do_log:
                    log.debug(f'Converted pint units "<{units:~P}> {units:P}" '
                              f'to SysML units "<{units_attr.short_name or ""}> {units_attr.name}"')
                return units_attr

        # Remember that the search was unsuccessful
        if self.__class__._do_log:
            log.debug(f'Could not convert pint units "<{units:~P}> {units:P}" to SysML units')
        if cache_unknown:
            self._cache_units_map(units, _UNKNOWN_UNIT)

        # Raise an error if needed
        if raise_if_unknown_unit:
            raise UndefinedUnitError(str(units))

    @classmethod
    def parse_python_units(cls, units: Union[Unit, str] = None, raise_if_unknown_unit=True) -> Optional[Unit]:
        """Parses a str to Python/pint unit if needed. Returns None for dimensionless."""

        # Check if we already have a Unit object
        if isinstance(units, Unit):

            # Check if it is dimensionless
            if units == cls.dimensionless_units_pint:
                return

            return units

        # Check if the units are empty
        if not units:
            return

        # Try to parse the units using pint
        try:
            parsed_units = ureg(units).units

            # Check if dimensionless
            if parsed_units == cls.dimensionless_units_pint:
                return

            return parsed_units

        except UndefinedUnitError:
            if raise_if_unknown_unit:
                raise

        except Exception:
            if raise_if_unknown_unit:
                raise UndefinedUnitError(units)

        if cls._do_log:
            log.debug(f'Could not parse "{units}" to pint units')

    def quantity(self, value: float, units: Unit = None) -> Quantity:
        """Quantity object factory"""
        return ureg.Quantity(value, units or self.dimensionless_units_pint)

    def _get_cache_from_pint(self, pint_units: Unit, raise_if_unknown_unit=True) -> Optional[syside.AttributeUsage]:
        units_attr_key = self._load_cache_from_pint(pint_units, raise_if_unknown_unit=raise_if_unknown_unit)
        if units_attr_key is not None:
            return self._sysml_obj_map[units_attr_key]

    @classmethod
    def _load_cache_from_pint(cls, pint_units: Unit, raise_if_unknown_unit=True) -> Optional[str]:

        # Check the cache
        if pint_units not in cls._pint_sysml_units_map:
            return

        units_attr_key = cls._pint_sysml_units_map[pint_units]

        # If the SysML units were unknown, raise if requested or return None
        if units_attr_key == _UNKNOWN_UNIT:
            if raise_if_unknown_unit:
                raise UndefinedUnitError(str(pint_units))
            return

        return units_attr_key

    @classmethod
    def _get_cache_from_sysml(cls, units_attr: syside.AttributeUsage, raise_if_unknown_unit=True) -> Optional[Unit]:

        # Check the cache
        units_attr_key = cls._sysml_attr_key(units_attr)
        if units_attr_key not in cls._sysml_pint_units_map:
            return

        pint_units = cls._sysml_pint_units_map[units_attr_key]

        # If the pint units were unknown, raise if requested or return None
        if pint_units == _UNKNOWN_UNIT:
            if raise_if_unknown_unit:
                raise UndefinedUnitError(units_attr.name)
            return

        return pint_units

    @staticmethod
    def _sysml_attr_key(sysml_attr: syside.AttributeUsage):
        if sysml_attr == _UNKNOWN_UNIT or isinstance(sysml_attr, str):
            return sysml_attr
        return str(sysml_attr.qualified_name)

    @classmethod
    def _cache_units_map(cls, pint_units: Union[Unit, _UNKNOWN_UNIT],
                         sysml_attr: Union[syside.AttributeUsage, str, _UNKNOWN_UNIT]):

        sysml_attr_key = cls._sysml_attr_key(sysml_attr)

        if pint_units in cls._pint_sysml_units_map or sysml_attr_key in cls._sysml_pint_units_map:
            return

        if pint_units != _UNKNOWN_UNIT:
            cls._pint_sysml_units_map[pint_units] = sysml_attr_key
        if sysml_attr_key != _UNKNOWN_UNIT:
            cls._sysml_pint_units_map[sysml_attr_key] = pint_units

    def _get_sysml_units_map(self):
        sysml_alias_map = {}
        sysml_units_map = {}
        sysml_object_map = {}

        # Loop over all unit elements
        for library in self.units_libraries:
            for units_attr in library.owned_elements:
                if (isinstance(units_attr, syside.AttributeUsage) and
                        (units_attr.specializes(self.unit_base_def) or units_attr.specializes(self.scale_base_def))):

                    units_attr_key = self._sysml_attr_key(units_attr)
                    if units_attr_key in sysml_alias_map:
                        continue
                    sysml_alias_map[units_attr_key] = []
                    sysml_object_map[units_attr_key] = units_attr

                    if units_attr.short_name:
                        sysml_units_map[units_attr.short_name.strip()] = units_attr_key
                        sysml_alias_map[units_attr_key].append(units_attr.short_name.strip())
                    if units_attr.name:
                        sysml_units_map[units_attr.name.strip()] = units_attr_key
                        sysml_alias_map[units_attr_key].append(units_attr.name.strip())

        # Loop over all alias elements
        for library in self.units_libraries:
            for alias, units_attr in library.children:
                # An alias is simply a membership relationship pointing to the element it is aliasing
                # The relationship has the name declared
                if alias.__class__ == syside.Membership:

                    units_attr_key = self._sysml_attr_key(units_attr)
                    if units_attr_key not in sysml_alias_map:
                        continue

                    if alias.name:
                        sysml_alias_map[units_attr_key].append(alias.name.strip())
                        sysml_units_map[alias.name.strip()] = units_attr_key
                    if alias.short_name:
                        sysml_alias_map[units_attr_key].append(alias.short_name.strip())
                        sysml_units_map[alias.short_name.strip()] = units_attr_key

        return sysml_alias_map, sysml_units_map, sysml_object_map

    @classmethod
    def _init_mappings(cls, sysml_units_map, sysml_alias_map):
        # Check if the caches are already initialized
        if len(cls._pint_sysml_units_map) > 0:
            return
        cls._sysml_units_map = sysml_units_map
        cls._sysml_alias_map = sysml_alias_map

        # Explicitly cache some mappings
        for pint_str, sysml_str in [
            ('degC', '°C_abs'),
            ('delta_degC', '°C'),
            ('degF', '°F_abs'),
            ('delta_degF', '°F'),
            ('kph', 'km/h'),
            ('mph', 'mph'),
            ('VA', 'V⋅A'),
            ('Wh', 'W⋅h'),
            ('m/s²', 'm/s²'),
        ]:
            cls._cache_units_map(cls.parse_python_units(pint_str), sysml_units_map[sysml_str])

        # Remove some units of measure that are represented by duplicate base units
        for remove_attr_from_map in [
            'var',  # V*A
            'octet',  # byte
            'octet per second',  # byte per second
            'm²⋅A',  # A*m**2
            'ua',  # astronomical unit, conflict with microyear in pint
            'J⋅s⁻¹',  # J/s
            'm⋅s⁻¹',  # m/s
            'mol⋅kg⁻¹',  # mol/kg
            'mol⋅m⁻³',  # mol/m3
            'ft⋅lbf',
            'kg⁻¹⋅s⋅A',
            'lbf⋅in/in',
            'circular mil',
            'unit pole',
        ]:
            units_attr_key = sysml_units_map[remove_attr_from_map]

            for alias in sysml_alias_map[units_attr_key]:
                del sysml_units_map[alias]
            del sysml_alias_map[units_attr_key]

        # Map all SysML units to pint units (more robust, because compound pint units are order-independent)
        cls._do_log = False
        for units_attr_key in sysml_alias_map:
            cls.get_python_units(units_attr_key, raise_if_unknown_unit=False)

        cls._do_log = True

    @staticmethod
    @register_unit_format('S')
    def _print_sysml_like(units: Unit, registry, **_):
        """Print multiplicative: m⋅s⁻² instead of m/s²"""
        from pint.delegates.formatter._format_helpers import pretty_fmt_exponent
        from pint.delegates.formatter._compound_unit_helpers import to_symbol_exponent_name

        return '⋅'.join([
            to_symbol_exponent_name((u, p), registry=registry)[0] +
            (pretty_fmt_exponent(p) if p != 1 else '')
            for u, p in units.items()])

    ##################################
    ### Quantity parsing functions ###
    ##################################

    def is_typed_by_quantity_value(self, attr: Union[syside.AttributeUsage, syside.AttributeDefinition]):
        return attr.specializes(self.quantity_value_base_def)

    def get_quantity_value_units(self, quantity_value_attr: Union[syside.AttributeUsage, syside.AttributeDefinition],
                                 raise_if_unknown_unit=True) -> Optional[Unit]:
        """
        Get the default (pint) units of a QuantityValue or QuantityUnit.

        For example:
        - ISQBase::MassValue --> kg
        - ISQSpaceTime::SpeedValue --> m/s
        """

        # Get the attribute def
        if isinstance(quantity_value_attr, syside.AttributeUsage):
            for relationship, attr_def in quantity_value_attr.heritage:
                if isinstance(relationship, syside.FeatureTyping) and isinstance(attr_def, syside.AttributeDefinition):
                    quantity_value_attr = attr_def
                    break

        quantity_value_key = self._sysml_attr_key(quantity_value_attr)
        quantity_value_str = quantity_value_attr.name

        # Check cache
        if quantity_value_key in self._sysml_quantities_units_map:
            pint_units = self._sysml_quantities_units_map[quantity_value_key]

            if pint_units == _UNKNOWN_UNIT:
                if raise_if_unknown_unit:
                    raise UndefinedUnitError(quantity_value_str)
                return

            return pint_units

        pint_units = None

        # Get the quantity dimension: try directly from a QuantityUnit
        quantity_units_def = None
        quantity_dimension = self._get_feature_by_name(quantity_value_attr, 'quantityDimension')
        if quantity_dimension is not None:
            quantity_units_def = quantity_value_attr
        else:
            # Get it from the references quantity unit (of a QuantityValue)
            m_ref = self._get_feature_by_name(quantity_value_attr, 'mRef')
            if m_ref:
                for relationship, quantity_units in m_ref.heritage:
                    if isinstance(relationship, syside.FeatureTyping):

                        quantity_dimension = self._get_feature_by_name(quantity_units, 'quantityDimension')
                        if quantity_dimension is not None:
                            quantity_units_def = quantity_units

        # Check if the quantity units derive from the dimensionless units
        if quantity_units_def is not None and quantity_units_def.specializes(self.dimensionless_units_def_sysml):
            pint_units = self.dimensionless_units_pint

        if pint_units is None and quantity_dimension is not None:
            # Get the quantity power factors: the list of quantities and their exponents
            quantity_power_factors = self._get_feature_by_name(quantity_dimension, 'quantityPowerFactors')

            if quantity_power_factors.feature_value and quantity_power_factors.feature_value.value:
                power_factors = None
                try:
                    power_factors = self._simple_parse_value(quantity_power_factors.feature_value.value)

                    if not isinstance(power_factors, list):
                        power_factors = [power_factors]

                except ValueError:
                    pass

                # Loop over power factors (quantities + exponents)
                if power_factors is not None:
                    for power_factor in power_factors:
                        if not isinstance(power_factor, syside.AttributeUsage):
                            continue

                        # Get the quantity and its preferred units
                        quantity_feature = self._get_feature_by_name(power_factor, 'quantity')
                        quantity = self._simple_parse_value(quantity_feature.feature_value.value)

                        quantity_key = self._sysml_attr_key(quantity)
                        if quantity_key not in self._sysml_quantities_units_map:
                            raise ValueError(
                                f'Base quantity not found (while parsing {quantity_value_str}): {quantity_key}')
                        units = self._sysml_quantities_units_map[quantity_key]
                        if units is None:  # Dimensionless
                            continue

                        exponent_feature = self._get_feature_by_name(power_factor, 'exponent')
                        exponent = self._simple_parse_value(exponent_feature.feature_value.value)

                        pint_units_part = units ** exponent if exponent != 1 else units
                        if pint_units is None:
                            pint_units = pint_units_part
                        else:
                            pint_units *= pint_units_part

        # Check if the units were found
        if pint_units is not None:
            if self._do_log:
                log.debug(f'Found default pint units for SysML quantity "{quantity_value_str}": '
                          f'"<{pint_units:~P}> {pint_units:P}"')

            if pint_units == self.dimensionless_units_pint:
                pint_units = None

            self._sysml_quantities_units_map[quantity_value_key] = pint_units
            return pint_units

        # No units were found
        if self._do_log:
            log.debug(f'Could not convert SysML units "{quantity_value_str}" to pint units')
        self._sysml_quantities_units_map[quantity_value_key] = _UNKNOWN_UNIT

        # Raise an error if needed
        if raise_if_unknown_unit:
            raise UndefinedUnitError(quantity_value_str)

    @classmethod
    def _map_base_quantities(cls, system_of_quantities: syside.AttributeUsage, system_of_units: syside.AttributeUsage,
                             dimensionless_quantities: list):
        """
        Maps quantities (e.g. length, mass) from a SystemOfQuantities to default/preferred units (e.g. m, kg)
        in a SystemOfUnits.
        """

        # Get the quantities and units
        quantities = cls._get_feature_by_name(system_of_quantities, 'baseQuantities')
        units = cls._get_feature_by_name(system_of_units, 'baseUnits')
        if quantities is None or units is None:
            raise ValueError(f'Malformed base quantities/units: '
                             f'{system_of_quantities.qualified_name}, {system_of_units.qualified_name}')

        assert quantities.feature_value and quantities.feature_value.value
        quantities = cls._simple_parse_value(quantities.feature_value.value)
        assert units.feature_value and units.feature_value.value
        units = cls._simple_parse_value(units.feature_value.value)

        assert len(quantities) == len(units)

        # Map quantities to units
        quantities_units_map = {}
        for i, quantity in enumerate(quantities):
            unit = units[i]
            pint_units = cls.get_python_units(unit)

            # Map quantity name (L, M, etc.) to default units
            quantities_units_map[cls._sysml_attr_key(quantity)] = pint_units

            # Map quantity type (LengthValue, MassValue, etc.) to default units
            quantity_value_type = None
            for relationship, heritage in quantity.heritage:
                if isinstance(relationship, syside.FeatureTyping) and heritage.name.endswith('Value'):
                    quantity_value_type = heritage
            if quantity_value_type is None:
                raise ValueError(f'Malformed base quantity: {quantity.qualified_name}')
            quantities_units_map[cls._sysml_attr_key(quantity_value_type)] = pint_units

        # Map dimensionless quantities
        for dimensionless_quantity in dimensionless_quantities:
            quantities_units_map[cls._sysml_attr_key(dimensionless_quantity)] = None

        return quantities_units_map

    ########################
    ### Helper functions ###
    ########################

    @staticmethod
    def _get_feature_by_name(element: syside.Type, name: str) -> Optional[syside.Feature]:
        for feature in element.features:
            if feature.name == name:
                return feature

    @classmethod
    def _get_element_by_qualified_name(
            cls,
            model: syside.Model,
            doc_namespace_map: dict,
            qualified_name: str,
            kind: Type[syside.Element] = None,
            env: bool = False,
    ) -> Optional[syside.Element]:
        """
        Resolve a qualified name like "Pkg::SubPkg::ElementName".
        Traverses nested namespaces/packages until the final element is found.

        If `kind` is given, ensures the result is of that type.
        If `env` is True, also searches the environment (stdlib).
        """
        # Split the qualified name by '::'
        name_parts = [p.strip() for p in qualified_name.split("::") if p.strip()]
        if not name_parts:
            return None

        # Start from the root context (MODEL or ENVIRONMENT depending on env flag)
        current = cls._search_namespace(model, doc_namespace_map, name_parts[0], env=env)

        if current is None:
            return None

        # Walk down through nested parts
        for name_part in name_parts[1:]:
            found = None
            for owned in getattr(current, "owned_elements", []):
                if owned.name == name_part or (owned.short_name and owned.short_name == name_part):
                    found = owned
                    break
            if found is None:
                return None
            current = found

        # Check type if specified
        if kind and not isinstance(current, kind):
            return None

        return current

    @staticmethod
    def _search_namespace(model: syside.Model, doc_namespace_map: dict, name: str, env=False) \
            -> Optional[syside.Namespace]:
        """More efficient function to search for a root namespace (e.g. package) in all documents."""

        if (name, env) in doc_namespace_map:
            return doc_namespace_map[name, env]

        for doc_mutex in (model.environment.documents if env else model.documents):
            with doc_mutex.lock() as doc:
                root_node = doc.root_node
                for namespace_node in root_node.children.elements:
                    if namespace_node.name == name:

                        doc_namespace_map[name, env] = namespace_node
                        return namespace_node
