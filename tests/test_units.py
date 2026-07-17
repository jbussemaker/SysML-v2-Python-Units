import math
import pytest
import syside
import pathlib
from pint import OffsetUnitCalculusError
from sysmlv2_units import SysMLUnitsHelper, UndefinedUnitError, ureg


def _load_sysml_model(path):
    model, _ = syside.try_load_model([path])
    return model


@pytest.fixture(autouse=True)
def _reset_caches():
    SysMLUnitsHelper._sysml_units_map = {}
    SysMLUnitsHelper._sysml_alias_map = {}
    SysMLUnitsHelper._pint_sysml_units_map = {}
    SysMLUnitsHelper._sysml_pint_units_map = {}


@pytest.fixture
def empty_sysml_model():
    model, _ = syside.load_model([])
    model.documents.append(syside.Document.create_st(
        syside.DocumentOptions(url=syside.Url('memory://new'), language='sysml'),
    ))
    return model


@pytest.fixture
def units_tests_model():
    return _load_sysml_model(pathlib.Path(__file__).parent / 'units_tests.sysml')


_skip_pretty_print_parsing = {
    'femtometer',
    'femtometer/s**2',
}


def test_python_units(empty_sysml_model):
    # Create the units helper
    units_helper = SysMLUnitsHelper(empty_sysml_model)

    # Test parsing into pint Unit objects
    assert units_helper.parse_python_units() is None
    assert units_helper.parse_python_units(units_helper.dimensionless_units_pint) is None
    assert units_helper.parse_python_units(ureg.m) == ureg.m

    assert units_helper.parse_python_units('m') == ureg.m
    assert units_helper.parse_python_units('') is None

    # Test parsing an unknown units
    with pytest.raises(UndefinedUnitError):
        units_helper.parse_python_units('blabla')
    assert units_helper.parse_python_units('blabla', raise_if_unknown_unit=False) is None

    with pytest.raises(UndefinedUnitError):
        units_helper.parse_python_units('m/s^')
    assert units_helper.parse_python_units('m/s^', raise_if_unknown_unit=False) is None

    # Test parsing compound units
    assert units_helper.parse_python_units('m/s') == ureg('m/s').units
    assert units_helper.parse_python_units('m/s**2') == ureg('m/s^2').units
    assert units_helper.parse_python_units('m⋅s⁻²') == ureg('m/s^2').units

    # Test parsing pretty-printer units
    for pint_units_ in ureg:
        for append in ['', '/s**2']:
            if pint_units_+append in _skip_pretty_print_parsing:
                continue

            # Check if the pint unit can be converted to SysML units
            try:
                pint_units = ureg(pint_units_+append).units
            except OffsetUnitCalculusError:
                continue

            pretty_printed = f'{pint_units:~P}'
            parsed_pint_units = units_helper.parse_python_units(pretty_printed)
            assert parsed_pint_units == pint_units


def test_pint_sysml_printing():
    assert f'{ureg('m/s').units:S}' == 'm⋅s⁻¹'

    assert f'{ureg('A*m⁻²*K⁻²').units:S}' == 'A⋅K⁻²⋅m⁻²'
    assert f'{ureg('A*K⁻²*m⁻²').units:S}' == 'A⋅K⁻²⋅m⁻²'

    # Test parsing pretty-printer units
    for pint_units_ in ureg:
        for append in ['', '/s**2']:
            if pint_units_+append in _skip_pretty_print_parsing:
                continue

            # Check if the pint unit can be converted to SysML units
            try:
                pint_units = ureg(pint_units_+append).units
            except OffsetUnitCalculusError:
                continue

            pretty_printed = f'{pint_units:S}'
            parsed_pint_units = SysMLUnitsHelper.parse_python_units(pretty_printed)
            assert parsed_pint_units == pint_units


def test_get_sysml_units(empty_sysml_model):
    unknowns = []
    for _ in range(2):  # Repeat to test caching
        units_helper = SysMLUnitsHelper(empty_sysml_model)

        assert units_helper.get_sysml_units() is None

        sysml_map = {name: units_helper._sysml_obj_map[attr_key]
                     for name, attr_key in units_helper._sysml_units_map.items()}

        for _ in range(2):  # Repeat to test caching
            assert units_helper.get_sysml_units(ureg.m) == sysml_map['m']
            assert units_helper.get_sysml_units(ureg.kg) == sysml_map['kg']
            assert units_helper.get_sysml_units(ureg.ft) == sysml_map['ft']

            assert units_helper.get_sysml_units('m') == sysml_map['m']
            assert units_helper.get_sysml_units('kg') == sysml_map['kg']
            assert units_helper.get_sysml_units('ft') == sysml_map['ft']

            assert units_helper.get_sysml_units(units_helper.parse_python_units('m/s')) == sysml_map['m/s']
            assert units_helper.get_sysml_units('m/s') == sysml_map['m/s']
            assert units_helper.get_sysml_units('m/s^2') == sysml_map['m⋅s⁻²']

            assert units_helper.get_sysml_units(ureg.Pa) == sysml_map['Pa']
            assert units_helper.get_sysml_units('Pa') == sysml_map['Pa']

            assert units_helper.get_sysml_units('Btu') == sysml_map['Btu']

            assert units_helper.get_sysml_units('degC') == sysml_map['°C_abs']
            assert units_helper.get_sysml_units('degF') == sysml_map['°F_abs']
            assert units_helper.get_sysml_units('delta_degC') == sysml_map['°C']
            assert units_helper.get_sysml_units('delta_degF') == sysml_map['°F']
            assert units_helper.get_sysml_units('K') == sysml_map['K']
            assert units_helper.get_sysml_units('degR') == sysml_map['°R']

            assert units_helper.get_sysml_units(ureg.nmi) == sysml_map['nmi']
            assert units_helper.get_sysml_units(ureg.nmi) == sysml_map['NM']

            # Loop over all pint units
            unknowns = []
            for pint_units_ in ureg:
                # Check if the pint unit can be converted to SysML units
                pint_units = ureg[pint_units_].units
                units_attr = units_helper.get_sysml_units(pint_units, raise_if_unknown_unit=False)
                if units_attr is None:
                    unknowns.append(f'<{pint_units:~P}> {pint_units:P}')
                    continue

                # Check if the SysML unit will be converted back to the same pint unit
                converted_pint_units = units_helper.get_python_units(units_attr, raise_if_unknown_unit=False)
                if 1*converted_pint_units != 1*pint_units:
                    raise RuntimeError(f'Reverse conversion error: {units_attr.name} != {pint_units} '
                                       f'(== {converted_pint_units})')

    print('PINT->SYSML UNKNOWNS:\n'+'\n'.join(unknowns))

    # Define a custom pint unit and check that it will indeed not be recognized by SysML
    ureg.define('blabla_units = 2 * kg')
    assert units_helper.parse_python_units('blabla_units') is not None
    for _ in range(2):
        with pytest.raises(UndefinedUnitError):
            units_helper.get_sysml_units('blabla_units')
        assert units_helper.get_sysml_units('blabla_units', raise_if_unknown_unit=False) is None


def test_get_python_units(empty_sysml_model):
    unknowns = []
    for _ in range(2):
        units_helper = SysMLUnitsHelper(empty_sysml_model)

        assert units_helper.get_python_units(units_helper.dimensionless_units_sysml) is None

        sysml_map = {name: units_helper._sysml_obj_map[attr_key]
                     for name, attr_key in units_helper._sysml_units_map.items()}

        for i in range(2):
            assert units_helper.get_python_units(sysml_map['m']) == ureg.m
            assert units_helper.get_python_units(sysml_map['kg']) == ureg.kg
            assert units_helper.get_python_units(sysml_map['ft']) == ureg.ft
            assert units_helper.get_python_units(sysml_map['Pa']) == ureg.Pa
            assert units_helper.get_python_units(sysml_map['Btu']) == ureg.Btu

            assert units_helper.get_python_units(sysml_map['m/s']) == units_helper.parse_python_units('m/s')
            assert units_helper.get_python_units(sysml_map['m⋅s⁻²']) == units_helper.parse_python_units('m/s^2')
            assert units_helper.get_python_units(sysml_map['m⋅s⁻²']) == units_helper.parse_python_units('m⋅s⁻²')

            with pytest.raises(UndefinedUnitError):
                units_helper.get_python_units(sysml_map['Btu_39°F'])
            assert units_helper.get_python_units(sysml_map['Btu_39°F'], raise_if_unknown_unit=False) is None

            assert units_helper.get_python_units(sysml_map['°C_abs']) == ureg.degC
            assert units_helper.get_python_units(sysml_map['°F_abs']) == ureg.degF
            assert units_helper.get_python_units(sysml_map['°C']) == ureg.delta_degC
            assert units_helper.get_python_units(sysml_map['°F']) == ureg.delta_degF
            assert units_helper.get_python_units(sysml_map['K']) == ureg.K
            assert units_helper.get_python_units(sysml_map['°R']) == ureg.degR

            assert units_helper.get_python_units(sysml_map['nmi']) == ureg.nmi
            assert units_helper.get_python_units(sysml_map['NM']) == ureg.nmi

            unknowns = []
            for units_attr_key in units_helper._sysml_alias_map:
                units_attr = units_helper._sysml_obj_map[units_attr_key]
                pint_units = units_helper.get_python_units(units_attr, raise_if_unknown_unit=False)
                if pint_units is None:
                    unknowns.append(f'<{units_attr.short_name or ""}> {units_attr.name}')
                    continue

                converted_units_attr = units_helper.get_sysml_units(pint_units, raise_if_unknown_unit=False)
                if converted_units_attr != units_attr:
                    raise RuntimeError(f'Reverse conversion error: {pint_units} != {units_attr.name} '
                                       f'(== {converted_units_attr.name})')

    print('SYSML->PINT UNKNOWNS:\n'+'\n'.join(unknowns))


def test_reference_printer(empty_sysml_model):
    # Make sure caches are initialized
    units_helper = SysMLUnitsHelper(empty_sysml_model)

    # Create an attribute with a quantity as value
    with empty_sysml_model.documents[0].lock() as doc:
        root = doc.root_node

        _, attribute = root.children.append(syside.OwningMembership, syside.AttributeUsage)
        attribute.declared_name = 'mass'

        units_helper.set_value_and_units(attribute, 3.14, 'kg')

        sysml_text = SysMLUnitsHelper.to_text(attribute)
        assert sysml_text.strip() == 'attribute mass = 3.14 [SI::kg];'


def test_get_quantity(units_tests_model):
    units_helper = SysMLUnitsHelper(units_tests_model)

    with units_tests_model.documents[0].lock() as doc:
        package = doc.root_node.children.elements[0]
        assert isinstance(package, syside.Package)
        elements = package.children.elements

        for _ in range(2):
            attr: syside.AttributeUsage = elements[3]
            assert attr.name == 'intNoUnits'
            assert units_helper.get_units(attr)[0] is None
            assert units_helper.get_quantity(attr) == units_helper.quantity(1.0)

            attr = elements[4]
            assert attr.name == 'rationalNoUnits'
            assert units_helper.get_units(attr) == (None, None)
            assert units_helper.get_quantity(attr) == units_helper.quantity(1.0)

            attr = elements[5]
            assert attr.name == 'mass1'
            assert units_helper.get_units(attr) == (ureg.kg, units_helper.get_sysml_units(ureg.kg))
            assert units_helper.get_quantity(attr) == ureg.Quantity(1.0, ureg.kg)

            attr = elements[6]
            assert attr.name == 'mass2'
            assert units_helper.get_units(attr)[0] == ureg.kg
            assert units_helper.get_quantity(attr) == ureg.Quantity(1.0, ureg.kg)

            attr = elements[7]
            assert attr.name == 'mass3'
            assert units_helper.get_units(attr)[0] == ureg.kg
            assert units_helper.get_quantity(attr) == ureg.Quantity(1.0, ureg.kg)

            attr = elements[8]
            assert attr.name == 'massFlow'
            assert units_helper.get_units(attr)[0]*1 == ureg('kg/s')
            assert units_helper.get_quantity(attr) == ureg('1.5 kg/s')

            attr = elements[9]
            assert attr.name == 'speedDef'
            assert units_helper.get_units(attr)[0]*1 == ureg('m/s')
            assert units_helper.get_units(attr)[1] == units_helper.get_sysml_units('m/s')
            assert units_helper.get_quantity(attr) == ureg('1 m/s')

            attr = elements[10]
            assert attr.name == 'speedAdhoc'
            assert units_helper.get_units(attr)[0]*1 == ureg('m/s')
            assert units_helper.get_units(attr)[1] is None
            assert units_helper.get_quantity(attr) == ureg('1 m/s')

            attr = elements[11]
            assert attr.name == 'speedKph'
            assert units_helper.get_units(attr)[0]*1 == ureg('km/h')
            assert units_helper.get_quantity(attr) == ureg('1 km/h')

            attr = elements[12]
            assert attr.name == 'pressureUS'
            assert units_helper.get_units(attr)[0]*1 == ureg('psi')
            assert units_helper.get_quantity(attr) == ureg('100 psi')

            attr = elements[13]
            assert attr.name == 'pressureSI'
            assert units_helper.get_units(attr)[0]*1 == ureg('Pa')
            assert units_helper.get_quantity(attr) == ureg('100 Pa')

            attr = elements[14]
            assert attr.name == 'pressureAdhoc'
            assert units_helper.get_units(attr)[0]*1 == ureg('Pa')
            assert units_helper.get_quantity(attr) == ureg('100 Pa')

            attr = elements[15]
            assert attr.name == 'tempShort'
            assert units_helper.get_units(attr)[0]*1 == ureg('degC')
            assert units_helper.get_quantity(attr) == ureg.Quantity(100, ureg.degC)

            attr = elements[16]
            assert attr.name == 'tempDeltaShort'
            assert units_helper.get_units(attr)[0]*1 == ureg('delta_degC')
            assert units_helper.get_quantity(attr) == ureg.Quantity(100, ureg.delta_degC)

            attr = elements[17]
            assert attr.name == 'tempLong'
            assert units_helper.get_units(attr)[0]*1 == ureg('degC')
            assert units_helper.get_quantity(attr) == ureg.Quantity(100, ureg.degC)

            attr = elements[18]
            assert attr.name == 'btuAttr'
            with pytest.raises(UndefinedUnitError):  # Btu_60 F is not known by pint
                assert units_helper.get_units(attr)
            assert units_helper.get_units(attr, raise_if_unknown_unit=False) == \
                (None, units_helper._sysml_obj_map[units_helper._sysml_units_map['Btu_60°F']])

            with pytest.raises(UndefinedUnitError):
                assert units_helper.get_quantity(attr)
            assert units_helper.get_quantity(attr, raise_if_unknown_unit=False) == ureg.Quantity(10.)

            attr = elements[19]
            assert attr.name == 'negativeValNoUnits'
            assert units_helper.get_units(attr) == (None, None)
            assert units_helper.get_quantity(attr) == ureg.Quantity(-5)

            attr = elements[20]
            assert attr.name == 'negativeVal'
            assert units_helper.get_units(attr)[0] == ureg.kg
            assert units_helper.get_quantity(attr) == ureg.Quantity(-5, ureg.kg)

            attr = elements[21]
            assert attr.name == 'adhocQual'
            assert units_helper.get_units(attr)[0]*1 == ureg('kg/s')
            assert units_helper.get_quantity(attr) == ureg('5 kg/s')

            attr = elements[22]
            assert attr.name == 'adhocQualLong'
            assert units_helper.get_units(attr)[0]*1 == ureg('kg*m/s')
            assert units_helper.get_quantity(attr) == ureg('-5 kg*m/s')

            attr = elements[23]
            assert attr.name == 'adhocQualPower'
            assert units_helper.get_units(attr)[0]*1 == ureg('m/s^2')
            assert units_helper.get_quantity(attr) == ureg('10.0 m/s^2')

            attr = elements[24]
            assert attr.name == 'infValueNoUnit'
            assert units_helper.get_units(attr)[0] is None
            assert units_helper.get_quantity(attr) == ureg.Quantity(math.inf)

            attr = elements[25]
            assert attr.name == 'nanValueNoUnit'
            assert units_helper.get_units(attr)[0] is None
            quantity = units_helper.get_quantity(attr)
            assert math.isnan(quantity.magnitude)
            assert quantity.units == ureg.dimensionless

            attr = elements[26]
            assert attr.name == 'infValue'
            assert units_helper.get_units(attr)[0] == ureg.kg
            assert units_helper.get_quantity(attr) == ureg.Quantity(math.inf, ureg.kg)

            attr = elements[27]
            assert attr.name == 'nanValue'
            assert units_helper.get_units(attr)[0] == ureg.kg
            quantity = units_helper.get_quantity(attr)
            assert math.isnan(quantity.magnitude)
            assert quantity.units == ureg.kg

            attr = elements[28]
            assert attr.name == 'wrappedNegativeValue'
            assert units_helper.get_units(attr)[0] == ureg.m
            assert units_helper.get_quantity(attr) == ureg('-15 m')

            attr = elements[29]
            assert attr.name == 'units'
            assert units_helper.get_units(attr) == (ureg.kg, units_helper.get_sysml_units('kg'))
            with pytest.raises(ValueError):
                assert units_helper.get_quantity(attr)

            attr = elements[30]
            assert attr.name == 'attrRefUnits'
            assert units_helper.get_units(attr) == (ureg.kg, elements[29])
            assert units_helper.get_quantity(attr) == ureg('10 kg')

            attr = elements[31]
            assert attr.name == 'aliasUnits'
            assert units_helper.get_units(attr) == (ureg.nmi, units_helper.get_sysml_units('nmi'))
            assert units_helper.get_quantity(attr) == ureg('50 nmi')

            attr = elements[32]
            assert attr.name == 'units2'
            assert units_helper.get_units(attr) == (ureg.nmi, units_helper.get_sysml_units('nmi'))
            with pytest.raises(ValueError):
                assert units_helper.get_quantity(attr)

            attr = elements[33]
            assert attr.name == 'aliasRefUnits'
            assert units_helper.get_units(attr) == (ureg.nmi, elements[32])
            assert units_helper.get_quantity(attr) == ureg('25 nmi')

            attr = elements[34]
            assert attr.name == 'foot'

            membership, _ = package.children[34]
            assert isinstance(membership, syside.Membership)
            assert membership.name == 'units3'

            assert units_helper.get_units(attr) == (ureg.ft, units_helper.get_sysml_units('ft'))
            with pytest.raises(ValueError):
                assert units_helper.get_quantity(attr)

            attr = elements[35]
            assert attr.name == 'aliasRefUnits2'
            assert units_helper.get_units(attr) == (ureg.ft, units_helper.get_sysml_units('ft'))
            assert units_helper.get_quantity(attr) == ureg('26 ft')

            attr = elements[36]
            assert attr.name == 'units4'
            assert not units_helper.is_typed_by_quantity_value(attr)
            assert units_helper.get_units(attr) == (ureg.m, units_helper.get_sysml_units('m'))
            with pytest.raises(ValueError):
                assert units_helper.get_quantity(attr)

            attr = elements[37]
            assert attr.name == 'subsetUnits'
            assert units_helper.get_units(attr) == (ureg.m, elements[36])
            assert units_helper.get_quantity(attr) == ureg('30 m')

            attr = elements[38]
            assert attr.name == 'adhocUnits'
            assert not units_helper.is_typed_by_quantity_value(attr)
            assert units_helper.get_units(attr) == (ureg('m/s').units, None)
            with pytest.raises(ValueError):
                assert units_helper.get_quantity(attr)

            attr = elements[39]
            assert attr.name == 'adhocValue'
            assert units_helper.get_units(attr) == (ureg('m/s').units, elements[38])
            assert units_helper.get_quantity(attr) == ureg('22 m/s')

            attr = elements[40]
            assert attr.name == 'massValue'
            assert units_helper.is_typed_by_quantity_value(attr)
            assert units_helper.get_quantity_value_units(attr) == ureg.kg
            assert units_helper.get_units(attr) == (ureg.kg, None)
            with pytest.raises(ValueError):
                assert units_helper.get_quantity(attr)

            attr = elements[41]
            assert attr.name == 'speedValue'
            assert units_helper.is_typed_by_quantity_value(attr)
            assert units_helper.get_quantity_value_units(attr) == ureg('m/s').units
            assert units_helper.get_units(attr) == (ureg('m/s').units, None)
            with pytest.raises(ValueError):
                assert units_helper.get_quantity(attr)

            attr = elements[42]
            assert attr.name == 'soundValue'
            assert units_helper.is_typed_by_quantity_value(attr)
            assert units_helper.get_quantity_value_units(attr) is None
            assert units_helper.get_units(attr)[0] is None
            with pytest.raises(ValueError):
                assert units_helper.get_quantity(attr)

            attr = elements[43]
            assert attr.name == 'assignedMassValue'
            assert units_helper.is_typed_by_quantity_value(attr)
            assert units_helper.get_quantity_value_units(attr) == ureg.kg
            assert units_helper.get_units(attr) == (ureg.g, units_helper.get_sysml_units('g'))
            assert units_helper.get_quantity(attr) == ureg('100 g')


def test_set_quantity(units_tests_model):
    units_helper = SysMLUnitsHelper(units_tests_model)

    def _assert_get_quantity(do_raise=True):
        quantity_ = units_helper.get_quantity(attr, raise_if_unknown_unit=do_raise)
        if math.isnan(quantity.magnitude):
            assert math.isnan(quantity_.magnitude)
            assert quantity_.units == quantity.units
        else:
            assert quantity_ == quantity

    with units_tests_model.documents[0].lock() as doc:
        package = doc.root_node.children.elements[0]
        assert isinstance(package, syside.Package)
        elements = package.children.elements

        for attr in elements[3:]:
            print(attr.name)
            try:
                quantity = units_helper.get_quantity(attr)

                units, units_attr = units_helper.get_units(attr)

            except UndefinedUnitError:
                quantity = units_helper.get_quantity(attr, raise_if_unknown_unit=False)
                assert quantity.units == ureg.dimensionless

                units, units_attr = units_helper.get_units(attr, raise_if_unknown_unit=False)
                assert units_attr is not None

            except ValueError:  # For attributes with units as value (instead of a quantity) OR a QuantityValue type

                units, units_attr = units_helper.get_units(attr)

                if not units_helper.is_typed_by_quantity_value(attr):
                    units_helper.set_units(attr, units)
                    assert units_helper.get_units(attr)[0] == units

                    if units_attr is not None:
                        units_helper.set_units(attr, units_attr)
                        assert units_helper.get_units(attr) == (units, units_attr)

                continue

            if quantity.units == ureg.dimensionless:
                assert units is None
            else:
                assert units == quantity.units

            # Set by quantity
            units_helper.set_quantity(attr, quantity)
            _assert_get_quantity()

            # Set by value and SysML units attribute
            canon_units_attr = units_helper.get_sysml_units(quantity.units)
            units_helper.set_value_and_units(attr, quantity.magnitude, canon_units_attr)
            _assert_get_quantity()

            # Set by original units attribute
            if units_attr is not None:
                units_helper.set_value_and_units(attr, quantity.magnitude, units_attr)
                _assert_get_quantity(do_raise=False)

        print(units_helper.to_text(doc.root_node))
