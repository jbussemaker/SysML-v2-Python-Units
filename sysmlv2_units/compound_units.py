import math
import syside
import logging
from typing import Tuple, Optional, Union
from pint import Unit, UndefinedUnitError
from pint.util import UnitsContainer

from sysmlv2_units.converter import ureg
from sysmlv2_units.quantity_mapper import SysMLQuantityValueMapper

__all__ = ['SysMLCompoundUnitsHelper']

log = logging.getLogger('sysml.units')


class SysMLCompoundUnitsHelper(SysMLQuantityValueMapper):
    """
    Class with functions for dealing with compound units and quantities.
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

    def _build_units_expression(self, feature: syside.Feature, units: Unit, raise_if_unknown_unit=True):
        """Build a compound units expression and set it as the feature value of the provided feature."""

        # Get the list of units and their exponents
        units_exponents = list(units._units.unit_items())
        assert len(units_exponents) > 0

        # If there is only one unit-exponent pair, build the exponent expression
        if len(units_exponents) == 1:
            unit_str, exponent = units_exponents[0]

            # Find the units attribute
            units_attr = self.get_sysml_units(ureg.Unit(unit_str), raise_if_unknown_unit=raise_if_unknown_unit)
            if units_attr is None:
                units_attr = self.dimensionless_units_sysml

            # Check if we need to build an exponentiation
            unit_ref_feature = feature
            if exponent != 1:
                exponent_expression: syside.OperatorExpression
                _, exponent_expression = feature.feature_value_member.set_member_element(syside.OperatorExpression)
                exponent_expression.operator = syside.ExplicitOperator.ExponentCaret

                # Left-side: unit attribute reference
                _, unit_ref_feature = exponent_expression.children.append(syside.ParameterMembership, syside.Feature)

                # Right-side: exponent
                _, exponent_feature = exponent_expression.children.append(syside.ParameterMembership, syside.Feature)
                self._set_simple_value(exponent_feature, exponent)

            # Set the unit reference
            reference_expression: syside.FeatureReferenceExpression
            _, reference_expression = unit_ref_feature.feature_value_member.set_member_element(
                syside.FeatureReferenceExpression)

            reference_expression.referent_member.set_member_element(units_attr)
            return

        # Separate unit-exponent pairs
        left_side_units = Unit(UnitsContainer({u: e for u, e in units_exponents[:-1]}))
        right_side_units = Unit(UnitsContainer({units_exponents[-1][0]: units_exponents[-1][1]}))

        # Create the top-level multiplication operator expression
        mult_expression: syside.OperatorExpression
        _, mult_expression = feature.feature_value_member.set_member_element(syside.OperatorExpression)
        mult_expression.operator = syside.ExplicitOperator.Multiply

        # Left-side: all units except the last
        _, multi_left_side = mult_expression.children.append(syside.ParameterMembership, syside.Feature)
        self._build_units_expression(multi_left_side, left_side_units, raise_if_unknown_unit=raise_if_unknown_unit)

        # Right-side: the last unit-exponent pair
        _, multi_right_side = mult_expression.children.append(syside.ParameterMembership, syside.Feature)
        self._build_units_expression(multi_right_side, right_side_units, raise_if_unknown_unit=raise_if_unknown_unit)

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
