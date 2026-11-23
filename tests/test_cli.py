import shutil
import syside
import pytest
import pathlib
import tempfile
from sysmlv2_units.cli import cli
from sysmlv2_units.helper import SysMLHelper
from sysmlv2_units.units_helper import SysMLUnitsHelper, ureg
from pint import UndefinedUnitError, DimensionalityError, OffsetUnitCalculusError


@pytest.fixture
def tmp_testing_folder():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tests_path = pathlib.Path(__file__).parent.absolute()
        shutil.copytree(tests_path, tmp_dir, dirs_exist_ok=True)
        yield pathlib.Path(tmp_dir)


here = str(pathlib.Path(__file__).parent.absolute())


def test_read_write_model(tmp_testing_folder):
    model = SysMLHelper.load_workspace_model(tmp_testing_folder, print_diagnostics=True)

    index = SysMLHelper.create_name_index(model)

    for name, kind in [
        ('PartDef', syside.PartDefinition),
        ('attr1', syside.AttributeUsage),
        ('attr2', syside.AttributeUsage),
        ('attr3', syside.AttributeUsage),
        ('attr4', syside.AttributeUsage),
    ]:
        element = SysMLHelper.get_element_by_qualified_name(model, index, f'CLITesting::{name}')
        assert isinstance(element, kind)
        assert element.name == name

    tests_model = tmp_testing_folder / 'cli_tests.sysml'
    assert tests_model.exists()
    tests_model.unlink()

    units_helper = SysMLUnitsHelper(model)
    units_helper.write_document(element.document)

    assert tests_model.exists()


def test_list_units():
    try:
        cli(['--help'])
    except SystemExit:
        pass
    try:
        cli(['list_units', '--help'])
    except SystemExit:
        pass

    cli(['list_units'])


def test_list_quantity_types():
    try:
        cli(['list_quantity_types', '--help'])
    except SystemExit:
        pass

    cli(['list_quantity_types'])


def test_parse():
    try:
        cli(['parse', '--help'])
    except SystemExit:
        pass

    with pytest.raises(ValueError):
        cli(['parse', ''])

    cli(['parse', 'm'])
    cli(['parse', '1 m'])

    cli(['parse', 'ft', '--convert-to-units', 'm'])
    cli(['parse', '1 ft', '--convert-to-units', 'm'])
    cli(['parse', '3 ft', '--convert-to-units', 'm'])
    cli(['parse', '3 foot', '--convert-to-units', 'meter'])

    with pytest.raises(UndefinedUnitError):
        cli(['parse', 'blabla'])
    with pytest.raises(DimensionalityError):
        cli(['parse', 'm', '--convert-to-units', 's'])

    for i, pint_units_ in enumerate(ureg):
        if i == 20:
            break
        for append in ['', '/s**2']:
            # if pint_units_+append in _skip_pretty_print_parsing:
            #     continue

            # Check if the pint unit can be converted to SysML units
            try:
                pint_units = ureg(pint_units_+append).units
            except OffsetUnitCalculusError:
                continue

            cli(['parse', f'{pint_units:~P}'])
            cli(['parse', f'3.14 {pint_units:~P}'])


def _load_get_quantity_value(workspace_dir, qualified_name):
    model = SysMLHelper.load_workspace_model(workspace_dir)
    units_helper = SysMLUnitsHelper(model, graceful_if_sysml_unsupported=True)
    element = SysMLHelper.get_element_by_qualified_name(model, units_helper._model_name_index, qualified_name, env=False)
    assert element is not None
    return units_helper.get_quantity_or_units(element, raise_if_unknown_unit=False)


def test_get():
    try:
        cli(['get', '--help'])
    except SystemExit:
        pass

    cli(['get', here, 'CLITesting::attr1'])
    cli(['get', here, 'CLITesting::attr2'])
    cli(['get', here, 'CLITesting::attr3'])
    cli(['get', here, 'CLITesting::attr4'])
    cli(['get', here, 'CLITesting::attr5'])

    assert _load_get_quantity_value(here, 'CLITesting::attr1') is None
    assert _load_get_quantity_value(here, 'CLITesting::attr2') == ureg.kg
    assert _load_get_quantity_value(here, 'CLITesting::attr3') == ureg('3.14 m/s')
    assert _load_get_quantity_value(here, 'CLITesting::attr4') is None
    assert _load_get_quantity_value(here, 'CLITesting::attr5') == ureg.kg


def test_set(tmp_testing_folder):
    try:
        cli(['set', '--help'])
    except SystemExit:
        pass

    loc = str(tmp_testing_folder)

    with pytest.raises(ValueError):
        cli(['set', loc, 'CLITesting::attr1', ''])
    assert _load_get_quantity_value(loc, 'CLITesting::attr1') is None

    cli(['set', loc, 'CLITesting::attr1', 'kg'])
    assert _load_get_quantity_value(loc, 'CLITesting::attr1') == ureg.kg
    cli(['set', loc, 'CLITesting::attr1', '3.14 kg'])
    assert _load_get_quantity_value(loc, 'CLITesting::attr1') == ureg('3.14 kg')

    cli(['set', loc, 'CLITesting::attr2', '42 m/s'])
    assert _load_get_quantity_value(loc, 'CLITesting::attr2') == ureg('42 m/s')
    cli(['set', loc, 'CLITesting::attr2', '3.14 s', '--dry-run'])
    assert _load_get_quantity_value(loc, 'CLITesting::attr2') == ureg('42 m/s')


def test_convert(tmp_testing_folder):
    try:
        cli(['convert', '--help'])
    except SystemExit:
        pass

    loc = str(tmp_testing_folder)

    cli(['convert', loc, 'CLITesting::attr1', 'kg'])
    assert _load_get_quantity_value(loc, 'CLITesting::attr1') == ureg.kg

    cli(['convert', loc, 'CLITesting::attr2', 'lbs'])
    assert _load_get_quantity_value(loc, 'CLITesting::attr2') == ureg.lbs

    cli(['convert', loc, 'CLITesting::attr3', 'kph'])
    assert _load_get_quantity_value(loc, 'CLITesting::attr3') == ureg('11.304 kph')
    with pytest.raises(DimensionalityError):
        cli(['convert', loc, 'CLITesting::attr3', 'kg'])

    cli(['convert', loc, 'CLITesting::attr4', 's'])

    cli(['convert', loc, 'CLITesting::attr5', 'ft'])
    assert _load_get_quantity_value(loc, 'CLITesting::attr5') == ureg.ft

    cli(['convert', loc, 'CLITesting::attr6', 's'])
    assert _load_get_quantity_value(loc, 'CLITesting::attr6') == ureg('3.14 s')

    cli(['convert', loc, 'CLITesting::attr6', ''])
    assert _load_get_quantity_value(loc, 'CLITesting::attr6') == ureg('3.14')
