import math
import syside
import logging
from typing import Tuple, Optional, Union
from pint import Unit, Quantity, UndefinedUnitError
from pint.util import UnitsContainer

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
                  raise_if_unknown_unit=True) -> float:
        """
        Set the feature value to a unit.

        Returns the scale of the associated value in case any unit conversion was needed.
        For example: 1 kW --> W with scale 1000 --> so multiply the value by 1000 --> 1000 W
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
            return 1.

        # Try to set compound units
        assert isinstance(units, Unit)
        return self._build_units_expression(feature, units, raise_if_unknown_unit=raise_if_unknown_unit)

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
                return feature, 1.

        else:
            units = self.parse_python_units(units, raise_if_unknown_unit=raise_if_unknown_unit)

            # Check if dimensionless
            if not units:
                return feature, 1.

        # Create a new Quantity expression
        quantity_expression: syside.OperatorExpression
        _, quantity_expression = feature.feature_value_member.set_member_element(syside.OperatorExpression)
        quantity_expression.operator = syside.ExplicitOperator.Quantity

        _, value_feature = quantity_expression.children.append(syside.ParameterMembership, syside.Feature)

        # Set the units
        units_feature: syside.Feature
        _, units_feature = quantity_expression.children.append(syside.ParameterMembership, syside.Feature)

        scale = self.set_units(units_feature, units, raise_if_unknown_unit=raise_if_unknown_unit)

        return value_feature, scale
