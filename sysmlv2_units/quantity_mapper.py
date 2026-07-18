import syside
import logging
from typing import Optional, Union, Dict
from pint import Unit, UndefinedUnitError

from sysmlv2_units.helper import SysMLHelper
from sysmlv2_units.converter import SysMLUnitsConverter, _UNKNOWN_UNIT

__all__ = ['SysMLQuantityValueMapper']

log = logging.getLogger('sysml.units')


class SysMLQuantityValueMapper(SysMLUnitsConverter):
    """
    Class with functions for mapping quantity value types to preferred units.
    """

    _sysml_quantities_units_map: Dict[str, str] = {}  # quantity attr key --> units attr key

    def __init__(self, model: syside.Model):
        super().__init__(model)
        doc_namespace_map = self._doc_namespace_map

        # Load some base elements from the SysML standard library
        self.quantity_value_base_def = SysMLHelper.get_element_by_qualified_name(model, doc_namespace_map,
            'Quantities::TensorQuantityValue', syside.AttributeDefinition, env=True)

        self.dimensionless_units_def_sysml = SysMLHelper.get_element_by_qualified_name(model, doc_namespace_map,
            'MeasurementReferences::DimensionOneUnit', syside.AttributeDefinition, env=True)

        # Initialize mapping from quantity value types to default units
        if len(self.__class__._sysml_quantities_units_map) == 0:
            isq = SysMLHelper.get_element_by_qualified_name(
                model, doc_namespace_map, 'ISQBase::isq', syside.AttributeUsage, env=True)
            si = SysMLHelper.get_element_by_qualified_name(
                model, doc_namespace_map, 'SI::si', syside.AttributeUsage, env=True)

            dimensionless_quantities = [
                SysMLHelper.get_element_by_qualified_name(model, doc_namespace_map,
                    'MeasurementReferences::DimensionOneValue', syside.AttributeDefinition, env=True),
                self.dimensionless_units_def_sysml,
            ]

            self.__class__._sysml_quantities_units_map = self._map_base_quantities(isq, si, dimensionless_quantities)

    def is_typed_by_quantity_value(self, attr: Union[syside.AttributeUsage, syside.AttributeDefinition]):
        """Check if an attribute is typed by a quantity base value."""
        return attr.specializes(self.quantity_value_base_def)

    def get_quantity_value_units(self, quantity_value_attr: Union[syside.AttributeUsage, syside.AttributeDefinition],
                                 raise_if_unknown_unit=True) -> Optional[Unit]:
        """
        Get the preferred (pint) units of a QuantityValue or QuantityUnit.

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
        quantity_dimension = SysMLHelper.get_feature_by_name(quantity_value_attr, 'quantityDimension')
        if quantity_dimension is not None:
            quantity_units_def = quantity_value_attr
        else:
            # Get it from the references quantity unit (of a QuantityValue)
            m_ref = SysMLHelper.get_feature_by_name(quantity_value_attr, 'mRef')
            if m_ref:
                for relationship, quantity_units in m_ref.heritage:
                    if isinstance(relationship, syside.FeatureTyping):

                        quantity_dimension = SysMLHelper.get_feature_by_name(quantity_units, 'quantityDimension')
                        if quantity_dimension is not None:
                            quantity_units_def = quantity_units

        # Check if the quantity units derive from the dimensionless units
        if quantity_units_def is not None and quantity_units_def.specializes(self.dimensionless_units_def_sysml):
            pint_units = self.dimensionless_units_pint

        if pint_units is None and quantity_dimension is not None:
            # Get the quantity power factors: the list of quantities and their exponents
            quantity_power_factors = SysMLHelper.get_feature_by_name(quantity_dimension, 'quantityPowerFactors')

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
                        quantity_feature = SysMLHelper.get_feature_by_name(power_factor, 'quantity')
                        quantity = self._simple_parse_value(quantity_feature.feature_value.value)

                        quantity_key = self._sysml_attr_key(quantity)
                        if quantity_key not in self._sysml_quantities_units_map:
                            raise ValueError(
                                f'Base quantity not found (while parsing {quantity_value_str}): {quantity_key}')
                        units = self._sysml_quantities_units_map[quantity_key]
                        if units is None:  # Dimensionless
                            continue

                        exponent_feature = SysMLHelper.get_feature_by_name(power_factor, 'exponent')
                        exponent = self._simple_parse_value(exponent_feature.feature_value.value)

                        # Parse Pint units and extend the overall units with this power factor
                        pint_units_part = units ** exponent if exponent != 1 else units
                        if pint_units is None:
                            pint_units = pint_units_part
                        else:
                            pint_units *= pint_units_part

        # Check if the units were found
        if pint_units is not None:
            if self.do_log:
                log.debug(f'Found default pint units for SysML quantity "{quantity_value_str}": '
                          f'"<{pint_units:~P}> {pint_units:P}"')

            if pint_units == self.dimensionless_units_pint:
                pint_units = None

            self._sysml_quantities_units_map[quantity_value_key] = pint_units
            return pint_units

        # No units were found
        if self.do_log:
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

        This provides the basis for `get_quantity_value_units`, which either looks up the base quantity types or
        composite quantity types, which all refer to the base types in the end.
        """

        # Get the quantities and units
        quantities = SysMLHelper.get_feature_by_name(system_of_quantities, 'baseQuantities')
        units = SysMLHelper.get_feature_by_name(system_of_units, 'baseUnits')
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
