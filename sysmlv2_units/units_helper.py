import math
import syside
import logging
from typing import Tuple, Optional, Union
from pint import Unit, Quantity, UndefinedUnitError

from sysmlv2_units.converter import ureg
from sysmlv2_units.quantity_mapper import SysMLQuantityValueMapper

__all__ = ['SysMLUnitsHelper', 'ureg', 'Unit', 'Quantity', 'UndefinedUnitError']

log = logging.getLogger('sysml.units')


class SysMLUnitsHelper(SysMLQuantityValueMapper):
    """
    Class with functions for dealing with units and quantities (value + units) in SysML v2.
    On the Python-side, it uses the [pint](https://pint.readthedocs.io/) package.

    Supports units from the SysML units library and units expressions (e.g. defining your own units by combining
    existing units through operations like division, multiplication, exponentiation, etc.).

    Raises an `UndefinedUnitError` if any unit parsing or conversion to/from SysML fails.
    """

    _binary_operators = {
        syside.Operator.Divide: '/',
        syside.Operator.Multiply: '*',
        syside.Operator.ExponentStar: '**',
        syside.Operator.ExponentCaret: '^',
    }

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

        # Return a Pint quantity object
        return self.quantity(value, units)

    def get_units(self, feature: Union[syside.Feature, syside.Expression], raise_if_unknown_unit=True) \
            -> Tuple[Optional[Unit], Optional[syside.AttributeUsage]]:
        """
        Gets the Pint units as set as a feature value or as part of a quantity expression.
        If none found but the feature derives from a quantity value base type, the preferred associated units are
        returned.

        Also returns the original units attribute that was set (if applicable).
        """

        # Check if the feature has a value
        if (isinstance(feature, syside.Feature) and not isinstance(feature, syside.Expression)
                and feature.feature_value is None):

            # If not, check if the feature itself is a unit
            if isinstance(feature, syside.AttributeUsage):
                # Check if the value is the dimensionless unit
                if feature == self.dimensionless_units_sysml:
                    return None, None

                # Check if the feature derives from a QuantityValue
                if self.is_typed_by_quantity_value(feature):
                    preferred_units = self.get_quantity_value_units(feature, raise_if_unknown_unit=raise_if_unknown_unit)
                    return preferred_units, None

                # Directly try to parse a unit set as the feature value
                parsed_units, units_attr = self._parse_units_attr(feature, raise_if_unknown_unit=raise_if_unknown_unit)
                if parsed_units is not None:
                    return parsed_units, units_attr

            raise ValueError(f'No feature value set on feature: {feature}')

        # Parse the unit that is part of a quantity
        _, _, units, units_attr = self._get_feature_value_units(feature, raise_if_unknown_unit=raise_if_unknown_unit)
        return units, units_attr

    def _get_feature_value_units(self, feature: Union[syside.Feature, syside.Expression], raise_if_unknown_unit=True) \
            -> Tuple[Optional[syside.Expression], bool, Optional[Unit], Optional[syside.AttributeUsage]]:
        """
        Parses a feature value and returns the (pint) units if set.
        Returns the (contained) feature that contains the value, so that should still be parsed.
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

        return value_expression, is_negation, units, units_attr

    def _parse_units_feature(self, units_feature: Union[syside.Feature, syside.Expression],
                             raise_if_unknown_unit=True) \
            -> Tuple[Union[Optional[Unit], int], Optional[syside.AttributeUsage]]:
        """
        Parses a feature that defines the units.
        Additionally, returns the units attribute that was set to define the unit if applicable.
        """

        # Get the expression to parse
        if isinstance(units_feature, syside.Expression):
            units_expression = units_feature
        else:
            units_expression = units_feature.feature_value.value

        # Parse a referenced units attribute, e.g.: SI::m
        if isinstance(units_expression, syside.FeatureReferenceExpression):

            # Get the referenced units attribute
            units_attr = units_expression.referent
            if not isinstance(units_attr, syside.AttributeUsage):
                return None, None

            # Parse the units attr to Pint units
            units, _ = self._parse_units_attr(units_attr, raise_if_unknown_unit=raise_if_unknown_unit)
            return units, units_attr

        # Parse an exponent value (as part of parsing a units expression)
        if (isinstance(units_expression, syside.LiteralInteger) or
                (isinstance(units_expression, syside.OperatorExpression)
                 and units_expression.operator == syside.Operator.Minus)):

            value = self._simple_parse_value(units_expression)
            return value, None

        # Recursively parse a units expression, e.g.: m*s^-1
        if (isinstance(units_expression, syside.OperatorExpression) and
                units_expression.operator in self._binary_operators and len(units_expression.children) == 2):

            # Get the left and right side features and the operator str
            left_side_feature, right_side_feature = units_expression.children.elements
            operator_str = self._binary_operators[units_expression.operator]

            # Parse the left and right side features into units or literal values
            left_side_units, _ = self._parse_units_feature(
                left_side_feature, raise_if_unknown_unit=raise_if_unknown_unit)
            right_side_units, _ = self._parse_units_feature(
                right_side_feature, raise_if_unknown_unit=raise_if_unknown_unit)

            # Check for unknown or dimensionless units
            if right_side_units is None:
                return left_side_units, None

            if left_side_units is None:
                left_side_units = self.dimensionless_units_pint

            # Parse Pint units
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
        """Create a new minus operator expression and return the value-containing feature."""

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

        # Set infinity value
        if math.isinf(value):
            value_feature.feature_value_member.set_member_element(syside.LiteralInfinity)

        # Set NaN value (null)
        elif value is None or math.isnan(value):
            value_feature.feature_value_member.set_member_element(syside.NullExpression)

        # Set integer value
        elif isinstance(value, int):
            _, literal = value_feature.feature_value_member.set_member_element(syside.LiteralInteger)
            literal.value = value

        # Set float (rational) value
        elif isinstance(value, float):
            _, literal = value_feature.feature_value_member.set_member_element(syside.LiteralRational)
            literal.value = value

        else:
            raise ValueError(f'Could not set simple value: {value}')
