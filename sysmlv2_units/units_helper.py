import syside
import logging
from typing import Tuple, Optional, Union
from pint import Unit, Quantity, UndefinedUnitError

from sysmlv2_units.converter import ureg
from sysmlv2_units.compound_units import SysMLCompoundUnitsHelper

__all__ = ['SysMLUnitsHelper', 'ureg', 'Unit', 'Quantity', 'UndefinedUnitError']

log = logging.getLogger('sysml.units')


class SysMLUnitsHelper(SysMLCompoundUnitsHelper):
    """
    Class with functions for dealing with units and quantities (value + units) in SysML v2.
    On the Python-side, it uses the [pint](https://pint.readthedocs.io/) package.

    Supports units from the SysML units library and units expressions (e.g. defining your own units by combining
    existing units through operations like division, multiplication, exponentiation, etc.).

    Raises an `UndefinedUnitError` if any unit parsing or conversion to/from SysML fails.

    If units are not supported in SysML, you can still save the units in the SysML model by setting
    `graceful_if_sysml_unsupported=True`. Unsupported units are then stored as a doc on the feature, and are therefore
    not semantically recognized by the SysML model anymore, so be careful with this behavior.
    For example: `attribute resolution = 2048 { doc units /* pixel */ }`
    """

    _binary_operators = {
        syside.Operator.Divide: '/',
        syside.Operator.Multiply: '*',
        syside.Operator.ExponentStar: '**',
        syside.Operator.ExponentCaret: '^',
    }

    _units_doc_name = '_units'

    ###################################################################
    ### SysML to Python (pint) conversion functions (SysML getters) ###
    ###################################################################

    def __init__(self, model: syside.Model, graceful_if_sysml_unsupported=False):
        super().__init__(model)
        self.graceful_if_sysml_unsupported = graceful_if_sysml_unsupported

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

        # Return a quantity object
        quantity = self.quantity(value, units)

        # Convert to other requested units if needed
        doc_units, has_units_doc = self.get_units_from_doc(feature, raise_if_unknown_unit=raise_if_unknown_unit)
        if has_units_doc and doc_units:
            return quantity.to(doc_units)

        return quantity

    def get_units(self, feature: Union[syside.Feature, syside.Expression], raise_if_unknown_unit=True) \
            -> Tuple[Optional[Unit], Optional[syside.AttributeUsage]]:
        """
        Gets the Pint units as set as a feature value or as part of a quantity expression.
        If none found but the feature derives from a quantity value base type, the preferred associated units are
        returned.

        Also returns the original units attribute that was set (if applicable).
        """

        # Check if a units doc is set, if yes we return this, because these would be the units in which we would want to
        # return the quantity value so it has higher priority than anything else
        doc_units, has_units_doc = self.get_units_from_doc(feature, raise_if_unknown_unit=raise_if_unknown_unit)
        if has_units_doc:
            return doc_units, None

        # Check if the feature has no value
        if (isinstance(feature, syside.Feature) and not isinstance(feature, syside.Expression)
                and feature.feature_value is None):

            # Check if the feature itself is a unit
            feature_value_error = None
            if isinstance(feature, syside.AttributeUsage):
                # Check if the value is the dimensionless unit
                if feature == self.dimensionless_units_sysml:
                    return None, None

                # Check if the feature derives from a QuantityValue
                if self.is_typed_by_quantity_value(feature):
                    preferred_units = self.get_quantity_value_units(feature, raise_if_unknown_unit=raise_if_unknown_unit)
                    return preferred_units, None

                # Check if the feature references or is an alias of a unit attribute
                try:
                    parsed_units, units_attr = self._parse_units_attr(feature, raise_if_unknown_unit=raise_if_unknown_unit)
                    if parsed_units is not None:
                        return parsed_units, units_attr

                except UndefinedUnitError as e:
                    feature_value_error = e

            # Return units from doc
            if has_units_doc:
                return doc_units, None

            if feature_value_error is not None:
                raise feature_value_error

            raise ValueError(f'No feature value set on feature: {feature}')

        # Parse the unit that is part of a quantity
        _, _, units, units_attr = self._get_feature_value_units(feature, raise_if_unknown_unit=raise_if_unknown_unit)
        return units, units_attr

    def _get_feature_value_units(self, feature: Union[syside.Feature, syside.Expression], raise_if_unknown_unit=True) \
            -> Tuple[Optional[syside.Expression], bool, Optional[Unit], Optional[syside.AttributeUsage]]:
        """
        Parses a feature value and returns the (pint) units if set.
        Returns the (contained) feature that contains the value, so that should still be parsed.

        Supports units defined as a str in a quantity expression: `attribute attr = 10['kg'];`
        Supports units defined as the feature's units doc: `attribute attr = 10 { doc units /* kg */ }`
        """

        # Get the value expression to parse
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

            # Extract the child parameters of the expression
            units_feature: syside.Feature
            value_feature, units_feature = value_expression.children.elements

            value_expression = value_feature.feature_value.value

            # Parse the units from the second parameter
            units, units_attr = self._parse_units_feature(units_feature, raise_if_unknown_unit=raise_if_unknown_unit)

        # Otherwise try to directly parse the value expression as units
        else:
            units, units_attr = self._parse_units_feature(value_expression, raise_if_unknown_unit=raise_if_unknown_unit)

            if units is not None and isinstance(units, Unit):
                value_expression = None
            else:
                units = units_attr = None

        # If no units were found, try to parse from units doc
        if units is None and units_attr is None and isinstance(feature, syside.Feature):
            units_from_docs, has_docs = self.get_units_from_doc(feature, raise_if_unknown_unit=raise_if_unknown_unit)
            if has_docs:
                units = units_from_docs

        return value_expression, is_negation, units, units_attr

    @classmethod
    def get_units_from_doc(cls, feature: syside.Feature, raise_if_unknown_unit=True) -> Tuple[Optional[Unit], bool]:
        """Parse units from the units doc. Also returns if the docs were set."""

        # Get units doc
        units_doc = cls._get_units_doc(feature)
        if units_doc is None:
            return None, False

        # Parse the unit
        units_str = units_doc.body or ''
        units = cls.parse_python_units(units_str, raise_if_unknown_unit=raise_if_unknown_unit)
        return units, True

    @classmethod
    def _get_units_doc(cls, feature: syside.Feature) -> Optional[syside.Documentation]:
        """Get the units doc element of a feature if it has one."""
        for doc_el in feature.children.elements:
            if isinstance(doc_el, syside.Documentation) and doc_el.name == cls._units_doc_name:
                return doc_el

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
        value_feature, scale = self._set_feature_value_quantity(
            feature, units, raise_if_unknown_unit=raise_if_unknown_unit)

        # Set the value
        self._set_simple_value(value_feature, value*scale)

    def set_units(self, feature: syside.Feature, units: Union[Unit, str, syside.AttributeUsage],
                  raise_if_unknown_unit=True, graceful_if_sysml_unsupported=None) -> float:
        """
        Set the feature value to a unit.

        Returns the scale of the associated value in case any unit conversion was needed.
        For example: 1 kW --> W with scale 1000 --> so multiply the value by 1000 --> 1000 W

        If the unit is not supported in SysML and `graceful_if_sysml_unsupported=True`, the unit is written as a
        literal string value.
        """

        # Parse units if needed
        if isinstance(units, str):
            units = self.parse_python_units(units, raise_if_unknown_unit=raise_if_unknown_unit)

        # Get the associated SysML units attribute
        if isinstance(units, syside.AttributeUsage):
            units_attr = units
        else:
            # If the units are unknown, compound or dimensionless, we instead use the units expression building code to
            # raise the actual error, because the `get_sysml_units` function does not distinguish between unknown and
            # compound units
            units_attr = self.get_sysml_units(units, raise_if_unknown_unit=False)

        if units_attr is not None:
            # Create and set the reference expression
            reference_expression: syside.FeatureReferenceExpression
            _, reference_expression = feature.feature_value_member.set_member_element(
                syside.FeatureReferenceExpression)

            reference_expression.referent_member.set_member_element(units_attr)
            self._remove_units_doc(feature)
            return 1.

        # Try to set compound units
        assert isinstance(units, Unit)
        unsupported_graceful = self.graceful_if_sysml_unsupported \
            if graceful_if_sysml_unsupported is None else graceful_if_sysml_unsupported

        try:
            scale = self._build_units_expression(
                feature, units, raise_if_unknown_unit=raise_if_unknown_unit or unsupported_graceful)

            # Save original units if the unit could not exactly be reconstructed (and the feature is not anonymous)
            if scale != 1 and feature.name:
                self.set_units_doc(units)
            else:
                self._remove_units_doc(feature)

            return scale

        except UndefinedUnitError:
            if not unsupported_graceful:
                raise

            # If the units are not supported by SysML, but we want to be graceful about it,
            # we set the units as a string literal
            self._remove_units_doc(feature)
            self._set_simple_value(feature, self.units_to_str(units, sysml_style=True))

    def set_units_doc(self, feature: syside.Feature, units: Union[Unit, str, syside.AttributeUsage] = None):
        """
        Set the units doc of a feature to the string representation of a unit. For example:
        ```
        attribute myAttr {
            doc units /* kg */
        }
        ```
        """

        # Convert to str
        units_str = self.units_to_str(units, sysml_style=True)
        if not units_str:
            units_str = self.dimensionless_units_str

        # Create docs if needed
        units_doc = self._get_units_doc(feature)
        if units_doc is None:
            _, units_doc = feature.children.insert(0, syside.OwningMembership, syside.Documentation)
            units_doc.declared_name = self._units_doc_name

        units_doc.body = units_str

    def _remove_units_doc(self, feature: syside.Feature):
        """Remove the units doc if set."""

        units_doc = self._get_units_doc(feature)
        if units_doc:
            feature.children.remove_element(units_doc)

    def _set_feature_value_quantity(self, feature: syside.Feature, units: Union[Unit, str, syside.AttributeUsage] = None,
                                    raise_if_unknown_unit=True) -> Tuple[syside.Feature, float]:
        """
        Optionally create a new quantity expression if a unit should be set.
        Returns the feature that should get the actual value (not set yet) and the scale of the value to be set.
        """

        # Parse units if needed
        if units and isinstance(units, syside.AttributeUsage):

            # Check if dimensionless
            if units == self.dimensionless_units_sysml:
                self._remove_units_doc(feature)
                return feature, 1.

        else:
            units = self.parse_python_units(units, raise_if_unknown_unit=raise_if_unknown_unit)

            # Check if dimensionless
            if not units:
                self._remove_units_doc(feature)
                return feature, 1.

        # Create a new Quantity expression
        quantity_expression: syside.OperatorExpression
        _, quantity_expression = feature.feature_value_member.set_member_element(syside.OperatorExpression)
        quantity_expression.operator = syside.ExplicitOperator.Quantity

        _, value_feature = quantity_expression.children.append(syside.ParameterMembership, syside.Feature)

        # Set the units
        units_feature: syside.Feature
        _, units_feature = quantity_expression.children.append(syside.ParameterMembership, syside.Feature)

        # Note: if the units are not supported, but we want to be graceful about it, we want the `set_units` function
        # to raise an error, so we can roll back the quantity expression here and set the units as a doc
        unsupported_graceful = self.graceful_if_sysml_unsupported
        try:
            scale = self.set_units(
                units_feature, units, raise_if_unknown_unit=raise_if_unknown_unit or unsupported_graceful,
                graceful_if_sysml_unsupported=False)

            # Save original units if the unit could not exactly be reconstructed
            if scale != 1:
                self.set_units_doc(feature, units)
            else:
                self._remove_units_doc(feature)

        except UndefinedUnitError:
            if not unsupported_graceful:
                raise

            # Roll back quantity expression and set units as a doc
            feature.feature_value_member.remove_member_element()
            value_feature = feature
            scale = 1.

            self.set_units_doc(feature, units)

        return value_feature, scale
