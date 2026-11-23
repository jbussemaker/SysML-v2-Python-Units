import sys
import syside
import pathlib
import tabulate
import argparse
from typing import Union
from sysmlv2_units.helper import SysMLHelper
from sysmlv2_units.units_helper import SysMLUnitsHelper, Quantity, Unit

GRACEFUL = True

# Exclude some ISQ libraries from reporting base quantity types, to avoid overwhelming
ISQ_EXCLUDE = {
    'ISQAtomicNuclear',
    'ISQChemistryMolecular',
    'ISQCondensedMatter',
    'ISQCharacteristicNumbers',
}


def list_units(_):
    """List all available units supported by this CLI, outputs: symbol, long name, dimensions, SysML v2 notation, quantity type"""

    units_helper = SysMLUnitsHelper(SysMLHelper.create_empty_model())

    data = []
    for unit in units_helper.get_mapped_units():
        data.append(_get_quantity_details(units_helper, unit, report_units_only=True))

    print(tabulate.tabulate(data, headers='keys', tablefmt='github'))


def list_quantity_types(_):
    """List all available quantity types supported by this CLI, outputs: name, description, preferred units, SysML v2 quantity types"""
    units_helper = SysMLUnitsHelper(SysMLHelper.create_empty_model())

    data = []
    for quantity_value_def in units_helper.get_quantity_value_defs():
        if quantity_value_def.owner.name in ISQ_EXCLUDE:
            continue

        name = quantity_value_def.name

        doc = (quantity_value_def.documentation.collect()[0].body or '').split('\n')
        description = ''
        for line in doc:
            if line.startswith('source:'):
                description = line[7:]
                if 'item ' in description:
                    description = ' '.join(description.split('item ')[1].split(' ')[1:])

        preferred_units = units_helper.get_quantity_value_units(quantity_value_def)
        preferred_units = units_helper.units_to_str(preferred_units) if preferred_units is not None else ''

        quantity_values = _get_quantity_values(units_helper, units_helper._sysml_attr_key(quantity_value_def))
        quantity_values = ('; '.join(quantity_values)) if len(quantity_values) > 0 else ''

        data.append(dict(name=name, description=description, preferred_units=preferred_units, quantity_types=quantity_values))

    print(tabulate.tabulate(data, headers='keys', tablefmt='github'))


def parse(args):
    """Parse a quantity (magnitude + units) or units string, and print information about it: symbol, long name, dimensions, SysML v2 notation, quantity type"""

    # Parse the quantity or units
    units_helper = SysMLUnitsHelper(SysMLHelper.create_empty_model(), graceful_if_sysml_unsupported=GRACEFUL)
    _parse_input_quantity_or_units(units_helper, args.quantity_or_units, args.convert_to_units)


def _parse_input_quantity_or_units(units_helper: SysMLUnitsHelper, value: str, convert_to_units: str = None):
    value = value.strip()
    if not value:
        raise ValueError('No value provided')
    print(f'Parsing: "{value}"')
    quantity = units_helper.parse_python_quantity(value)

    # Check if the user requested units or a quantity
    is_units = quantity.magnitude == 1 and not value.startswith('1')
    _report_quantity(units_helper, quantity, report_units_only=is_units)

    # Check if we need to convert
    if convert_to_units is not None:
        quantity = _convert_to_units(units_helper, quantity, convert_to_units)

    return quantity, is_units


def _convert_to_units(units_helper: SysMLUnitsHelper, quantity: Quantity, convert_to_units: str):
    print(f'Converting to units: "{convert_to_units}"')

    target_units = units_helper.parse_python_units(convert_to_units)

    if quantity.units == units_helper.dimensionless_units_pint:  # From dimensionless: just set the units
        quantity = units_helper.quantity(quantity.magnitude, target_units)
    elif target_units is None:  # To dimensionless: just remove the units
        quantity = units_helper.quantity(quantity.magnitude)
    else:
        quantity = quantity.to(target_units)

    _report_quantity(units_helper, quantity)
    return quantity


def _get_quantity_details(units_helper: SysMLUnitsHelper, quantity: Union[Quantity, Unit], report_units_only: bool = False):

    if isinstance(quantity, Unit):
        report_units_only = True
    units = quantity.units if isinstance(quantity, Quantity) else quantity

    data = {}
    if report_units_only:
        data['symbol'] = units_helper.units_to_str(units, sysml_style=True)
        data['name'] = f'{units:P}'
        data['dimensionality'] = f'{units.dimensionality:P}'

    else:
        data['quantity'] = units_helper.units_to_str(quantity, sysml_style=True)
        data['quantity_full'] = f'{quantity:P}'
        data['dimensionality'] = f'{quantity.dimensionality:P}'

    # Get SysML v2 notation
    with SysMLHelper.temporary_anonymous_feature(units_helper.model) as feature:
        if report_units_only:
            units_helper.set_units(feature, units)
        else:
            units_helper.set_quantity(feature, quantity)
        data['sysml'] = units_helper.to_text(feature, kerml_mode=True).strip().replace('feature = ', '').strip(';')

    # Get associated quantity base types
    units_attr = units_helper.get_sysml_units(units if isinstance(quantity, Unit) else quantity.units, raise_if_unknown_unit=False)
    if units_attr is not None:
        quantity_value_key = units_helper.get_units_quantity_value(units_attr)
        assert quantity_value_key is not None

        quantity_values = _get_quantity_values(units_helper, quantity_value_key)
        if len(quantity_values) > 0:
            data['quantity_base_types'] = '; '.join(quantity_values)

    return data


def _get_quantity_values(units_helper: SysMLUnitsHelper, quantity_value_key: str):
    quantity_values = units_helper.get_concrete_quantity_values(quantity_value_key)

    # Filter-out some ISQ libraries, and report all base types as "ISQ::*" for easy import
    filtered_quantity_values = [qv for qv in quantity_values if qv.split('::')[0] not in ISQ_EXCLUDE]
    quantity_values = filtered_quantity_values if len(filtered_quantity_values) > 0 else quantity_values
    quantity_values = ['::'.join(['ISQ']+qv.split('::')[1:]) for qv in quantity_values]

    return quantity_values


def _report_quantity(units_helper: SysMLUnitsHelper, quantity: Union[Quantity, Unit], report_units_only: bool = False,
                     skip_symbol=False):
    data = _get_quantity_details(units_helper, quantity, report_units_only=report_units_only)

    for i, (key, value) in enumerate(data.items()):
        if skip_symbol and i == 0:
            continue
        print(f'  {key} = {value}')


def get_quantity_or_units(args):
    """Gets quantity or units of the element at the qualified path"""
    _load_quantity_or_units(args)


def set_quantity_or_units(args):
    """Sets quantity or units of the element at the qualified path"""
    units_helper, element = _load_model_get_element(args)
    quantity, is_units = _parse_input_quantity_or_units(units_helper, args.quantity_or_units, args.convert_to_units)

    if is_units:
        units_helper.set_units(element, quantity.units)
    else:
        units_helper.set_quantity(element, quantity)

    _write_or_dry_run(units_helper, element, args)


def _write_or_dry_run(units_helper: SysMLUnitsHelper, element: syside.Feature, args):
    if args.dry_run:
        print(f'[DRY-RUN] Would-be element status:')
    else:
        path = units_helper.write_document(element.document)
        print(f'Updated element, document written: {path!s}')
    _print_element(units_helper, element)


def convert_quantity(args):
    """Converts quantity of the element at the qualified path to other units"""
    units_helper, element, quantity_or_units = _load_quantity_or_units(args)

    # If there is no value set or the value is a units literal: just overwrite the units
    if quantity_or_units is None or isinstance(quantity_or_units, Unit):
        only_set_units = True
        quantity, _ = _parse_input_quantity_or_units(units_helper, args.convert_to_units)
    else:
        only_set_units = False
        quantity = _convert_to_units(units_helper, quantity_or_units, args.convert_to_units)

    if only_set_units:
        units_helper.set_units(element, quantity.units)
    else:
        units_helper.set_quantity(element, quantity)

    _write_or_dry_run(units_helper, element, args)


def _load_quantity_or_units(args):
    units_helper, element = _load_model_get_element(args)
    units_or_quantity = units_helper.get_quantity_or_units(element, raise_if_unknown_unit=False)

    if units_or_quantity is not None:
        if isinstance(units_or_quantity, Quantity):
            print(f'Loaded quantity: {units_helper.units_to_str(units_or_quantity, sysml_style=True)}')
            _report_quantity(units_helper, units_or_quantity, report_units_only=False, skip_symbol=True)
            return units_helper, element, units_or_quantity

        elif isinstance(units_or_quantity, Unit):
            print(f'Loaded units: {units_helper.units_to_str(units_or_quantity, sysml_style=True)}')
            _report_quantity(units_helper, units_or_quantity, report_units_only=True, skip_symbol=True)
            return units_helper, element, units_or_quantity

    print(f'No value assigned to {element.qualified_name!s}')
    return units_helper, element, None


def _load_model_get_element(args):
    workspace_dir = args.workspace_folder.absolute()
    print(f'Loading model at: "{args.workspace_folder}"')
    model = SysMLHelper.load_workspace_model(workspace_dir)
    units_helper = SysMLUnitsHelper(model, graceful_if_sysml_unsupported=GRACEFUL)

    qualified_name = args.qualified_name
    print(f'Getting element at: {qualified_name}')
    element = SysMLHelper.get_element_by_qualified_name(model, units_helper._model_name_index, qualified_name, env=False)
    if element is None:
        raise RuntimeError(f'Element not found: {qualified_name}')
    if not isinstance(element, syside.Feature):
        raise RuntimeError(f'Element is not a feature: {qualified_name}')

    _print_element(units_helper, element)

    return units_helper, element


def _print_element(units_helper: SysMLUnitsHelper, element: syside.Feature):
    element_text = '\n  '.join(units_helper.to_text(element).strip().split('\n')[:3])
    print(f'  {element_text}')


def cli(args=None):
    # Force utf-8 output
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser('sysmlv2_units', description='CLI for working with SysML v2 quantities and units')
    subparsers = parser.add_subparsers(required=True)

    workspace_folder_kwargs = dict(
        type=pathlib.Path,
        help='SysML v2 workspace folder to load the model files from, "." for cwd')
    qualified_name_kwargs = dict(type=str, help='Qualified name of the SysML v2 element')
    dry_run_kwargs = dict(action='store_true', help='Only print the final element state, don\'t actually write anything')
    convert_units_kwargs = dict(type=str, help='Convert the quantity to these units')

    # list_units command
    parser_list_units = subparsers.add_parser('list_units', description=list_units.__doc__, help=list_units.__doc__)
    parser_list_units.set_defaults(func=list_units)

    # list_quantity_types command
    parser_list_quantity_types = subparsers.add_parser(
        'list_quantity_types', description=list_quantity_types.__doc__, help=list_quantity_types.__doc__)
    parser_list_quantity_types.set_defaults(func=list_quantity_types)

    # parse command
    parser_parse = subparsers.add_parser('parse', description=parse.__doc__, help=parse.__doc__)
    parser_parse.set_defaults(func=parse)

    parser_parse.add_argument('quantity_or_units', type=str,
                              help='Quantity (magnitude + units) or units to parse and print information about')
    parser_parse.add_argument('--convert-to-units', metavar='units', **convert_units_kwargs)

    # get command
    parser_get = subparsers.add_parser('get', description=get_quantity_or_units.__doc__, help=get_quantity_or_units.__doc__)
    parser_get.set_defaults(func=get_quantity_or_units)

    parser_get.add_argument('workspace_folder', **workspace_folder_kwargs)
    parser_get.add_argument('qualified_name', **qualified_name_kwargs)

    # set command
    parser_set = subparsers.add_parser('set', description=set_quantity_or_units.__doc__, help=set_quantity_or_units.__doc__)
    parser_set.set_defaults(func=set_quantity_or_units)

    parser_set.add_argument('workspace_folder', **workspace_folder_kwargs)
    parser_set.add_argument('qualified_name', **qualified_name_kwargs)
    parser_set.add_argument('quantity_or_units', type=str, help='Quantity (magnitude + units) or units to set')
    parser_set.add_argument('--convert-to-units', **convert_units_kwargs)
    parser_set.add_argument('--dry-run', **dry_run_kwargs)

    # convert command
    parser_convert = subparsers.add_parser('convert', description=convert_quantity.__doc__, help=convert_quantity.__doc__)
    parser_convert.set_defaults(func=convert_quantity)

    parser_convert.add_argument('workspace_folder', **workspace_folder_kwargs)
    parser_convert.add_argument('qualified_name', **qualified_name_kwargs)
    parser_convert.add_argument('convert_to_units', **convert_units_kwargs)
    parser_convert.add_argument('--dry-run', **dry_run_kwargs)

    # Parse arguments and run the function associated to the subcommand
    args = parser.parse_args(args)
    try:
        args.func(args)
    except Exception as e:
        if args is None:
            return _exit_error(e)
        print(f'[ERROR] {e}')
        raise


def _exit_error(e):
    print(f'[ERROR] {e}')
    exit(1)


if __name__ == '__main__':
    cli()
