import syside
import logging
from collections import OrderedDict
from typing import Optional, Union, Dict, List
from pint import Unit, Quantity, get_application_registry, UndefinedUnitError, register_unit_format

from sysmlv2_units.helper import SysMLHelper

__all__ = ['SysMLUnitsConverter', 'ureg', '_UNKNOWN_UNIT', 'CustomUndefinedUnitError']

log = logging.getLogger('sysml.units')

ureg = get_application_registry()
_UNKNOWN_UNIT = object()


class CustomUndefinedUnitError(UndefinedUnitError):

    def __init__(self, unit_names, msg: str):
        super().__init__(unit_names)
        self.msg = msg

    def __str__(self):
        return self.msg


class SysMLUnitsConverter:
    """
    Class with functions for converting units between SysML v2 and Python (using Pint).
    Only supports base units, not compound units.

    Raises an `UndefinedUnitError` if any unit parsing or conversion to/from SysML fails.
    """

    dimensionless_units_pint = ureg.dimensionless
    dimensionless_units_sysml_key = 'MeasurementReferences::one'

    _sysml_alias_map: Dict[str, List[str]] = {}  # units attr key --> list of alias names
    _sysml_units_map: Dict[str, str] = {}  # alias name --> units attr key

    _pint_sysml_units_map = {}
    _sysml_pint_units_map = {}

    _explicit_units_map = [  # Pint -> SysML
        ('degC', '°C_abs'),
        ('delta_degC', '°C'),
        ('degF', '°F_abs'),
        ('delta_degF', '°F'),
        ('kph', 'km/h'),
        ('mph', 'mph'),
        ('VA', 'V⋅A'),
        ('Wh', 'W⋅h'),
        ('m/s²', 'm/s²'),
    ]

    _units_remove_list = [  # Duplicate SysML units or otherwise wrongly-interpreted units
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
    ]

    do_log = False

    def __init__(self, model: syside.Model):
        self._doc_namespace_map = doc_namespace_map = {}

        # Load some base elements from the SysML standard library
        self.unit_base_def = SysMLHelper.get_element_by_qualified_name(model, doc_namespace_map,
            'MeasurementReferences::MeasurementUnit', syside.AttributeDefinition, env=True)
        self.scale_base_def = SysMLHelper.get_element_by_qualified_name(model, doc_namespace_map,
            'MeasurementReferences::MeasurementScale', syside.AttributeDefinition, env=True)

        self.dimensionless_units_sysml = SysMLHelper.get_element_by_qualified_name(model, doc_namespace_map,
            'MeasurementReferences::one', syside.AttributeUsage, env=True)
        self.__class__.dimensionless_units_sysml_key = self._sysml_attr_key(self.dimensionless_units_sysml)

        # Load the units libraries and initialize unit mapping caches
        self.units_libraries = [
            SysMLHelper.search_namespace(model, doc_namespace_map, 'SI', env=True),
            SysMLHelper.search_namespace(model, doc_namespace_map, 'USCustomaryUnits', env=True),
        ]
        sysml_alias_map, sysml_units_map, self._sysml_obj_map = self._get_sysml_units_map()
        self._init_mappings(sysml_units_map, sysml_alias_map)

        # Check if all base elements were found
        if any([prop is None for prop in [
            self.unit_base_def,
            self.scale_base_def,
            self.dimensionless_units_sysml,
        ]+self.units_libraries]):
            raise RuntimeError('Not all units helper elements found!')

    @classmethod
    def get_python_units(cls, units_attr: Union[syside.AttributeUsage, str], raise_if_unknown_unit=True,
                         cache_unknown=True) -> Optional[Unit]:
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
            if cls.do_log:
                log.debug(f'Converted SysML units "{units_attr_str}" to pint units "<{pint_units:~P}> {pint_units:P}"')

            cls._cache_units_map(pint_units, units_attr)
            return pint_units

        # No units were found
        msg = f'Could not convert SysML units "{units_attr_str}" to pint units'
        if cls.do_log:
            log.debug(msg)
        if cache_unknown:
            cls._cache_units_map(_UNKNOWN_UNIT, units_attr)

        # Raise an error if needed
        if raise_if_unknown_unit:
            raise CustomUndefinedUnitError(units_attr_str, msg=msg)

    def get_sysml_units(self, units: Union[Unit, str] = None, raise_if_unknown_unit=True, cache_unknown=True) \
            -> Optional[syside.AttributeUsage]:
        """Gets SysML units for the given Python/pint units. Returns None for dimensionless."""

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
                # Get and return the found units
                units_attr = self._sysml_obj_map[units_attr_key]
                assert units_attr != self.dimensionless_units_sysml

                self._cache_units_map(units, units_attr)
                if self.__class__.do_log:
                    log.debug(f'Converted pint units "<{units:~P}> {units:P}" '
                              f'to SysML units "<{units_attr.short_name or ""}> {units_attr.name}"')
                return units_attr

        # Remember that the search was unsuccessful
        msg = f'Could not convert pint units "<{units:~P}> {units:P}" to SysML units'
        if self.__class__.do_log:
            log.debug(msg)
        if cache_unknown:
            self._cache_units_map(units, _UNKNOWN_UNIT)

        # Raise an error if needed
        if raise_if_unknown_unit:
            raise CustomUndefinedUnitError(str(units), msg=msg)

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

        # Replace pretty-printed SysML-style multiplication with pint-style
        if isinstance(units, str):
            units = units.replace('⋅', '·')

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

        except Exception as e:
            if raise_if_unknown_unit:
                raise CustomUndefinedUnitError(units, msg=str(e))

        if cls.do_log:
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
                raise CustomUndefinedUnitError(str(pint_units), msg=f'Cannot map Pint units to SysML: {pint_units}')
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
                raise CustomUndefinedUnitError(units_attr.name, msg=f'Cannot map SysML to Pint units: {units_attr_key}')
            return

        return pint_units

    @staticmethod
    def _sysml_attr_key(sysml_attr: syside.AttributeUsage):
        """Normalize a SysMl attr to its qualified name,
        so that we can reuse the SysML-side cache across Syside model instances"""
        if sysml_attr == _UNKNOWN_UNIT or isinstance(sysml_attr, str):
            return sysml_attr
        return str(sysml_attr.qualified_name)

    @classmethod
    def _cache_units_map(cls, pint_units: Union[Unit, _UNKNOWN_UNIT],
                         sysml_attr: Union[syside.AttributeUsage, str, _UNKNOWN_UNIT]):
        """Add a mapping result to the cache"""

        sysml_attr_key = cls._sysml_attr_key(sysml_attr)

        if pint_units in cls._pint_sysml_units_map or sysml_attr_key in cls._sysml_pint_units_map:
            return

        if pint_units != _UNKNOWN_UNIT:
            cls._pint_sysml_units_map[pint_units] = sysml_attr_key
        if sysml_attr_key != _UNKNOWN_UNIT:
            cls._sysml_pint_units_map[sysml_attr_key] = pint_units

    def _get_sysml_units_map(self):
        """Get the initial SysML units map from the SysML v2 standard library."""

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
        """Initialize mappings for actual use by adding explicit mappings and removing faulty mappings."""

        # Check if the caches are already initialized
        if len(cls._pint_sysml_units_map) > 0:
            return
        cls._sysml_units_map = sysml_units_map
        cls._sysml_alias_map = sysml_alias_map

        # Explicitly cache some mappings
        for pint_str, sysml_str in cls._explicit_units_map:
            cls._cache_units_map(cls.parse_python_units(pint_str), sysml_units_map[sysml_str])

        # Remove some units of measure that are represented by duplicate base units
        for remove_attr_from_map in cls._units_remove_list:
            units_attr_key = sysml_units_map[remove_attr_from_map]

            for alias in sysml_alias_map[units_attr_key]:
                del sysml_units_map[alias]
            del sysml_alias_map[units_attr_key]

        # Map all SysML units to pint units (more robust, because compound pint units are order-independent)
        cls.do_log = False
        for units_attr_key in sysml_alias_map:
            cls.get_python_units(units_attr_key, raise_if_unknown_unit=False)

        cls.do_log = True

    ################################
    ### SysML printing functions ###
    ################################

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

        def get_name_pref(target: syside.Element, _: syside.Element) -> syside.NamePreference:
            # Check if the target is a unit
            if target.__class__ == syside.AttributeUsage:
                units_attr_key = cls._sysml_attr_key(target)
                if units_attr_key in alias_map:
                    # Tell the printer that we want to print the reference using the short name
                    return syside.NamePreference.Shortest

            # Otherwise print using regular settings
            return syside.NamePreference.Regular

        return syside.ReferencePrinter(get_name_pref)
