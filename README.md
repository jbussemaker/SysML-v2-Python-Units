# SysML v2 Python Units

[![Tests](https://github.com/jbussemaker/SysML-v2-Python-Units/workflows/Tests/badge.svg)](https://github.com/jbussemaker/SysML-v2-Python-Units/actions/workflows/tests.yml?query=workflow%3ATests)
[![PyPI](https://img.shields.io/pypi/v/sysmlv2-units.svg)](https://pypi.org/project/sysmlv2-units)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Convert units and quantities between standard [SysML v2](https://www.omg.org/sysml/sysmlv2/) and Python with
[Syside Automator](https://docs.sensmetry.com/automator/) and [Pint](https://pint.readthedocs.io/).

- Get/set quantity* as `attribute` value, specified using Pint `Quantity` objects
- Get/set unit as `attribute` value, specified using Pint `Unit` objects
- Supports numerical values/magnitudes, as well as `inf` (`*` in SysML v2) and `NaN` (set as `null` in SysML v2)
- Conversion functions between SysML v2 units and Pint `Unit`, and string parsing functions
- Derive base units for a quantity type, for example `kg` for an `ISQ::mass` quantity
- Syside Automator [`ReferencePrinter`](https://docs.sensmetry.com/python/latest/syside/ReferencePrinter.html) for
  printing unit references using their short name
- Extensive caching to make units lookup fast

*: a quantity is a combination of a numerical value (the "magnitude") and units, for example: `10 kg`, `-1.0 m/s**2`.

Note: this package uses [Syside Automator](https://docs.sensmetry.com/automator/) for parsing SysMl v2 models.
Syside Automator is commercial software, so you have to obtain a license first.
For academic uses you can request an [academic license](https://sensmetry.com/syside-pricing/).

## Installation

1. Install the package from PyPI:
   ```
   pip install sysmlv2-units
   ```
   Note: currently Syside Automator only supports Python 3.12
2. Make sure you [activate Syside Automator](https://docs.sensmetry.com/automator/install.html#activate-license)

## Usage

Refer to [the documentation](https://github.com/jbussemaker/SysML-v2-Python-Units/blob/main/documentation.ipynb).

## Citing

If you use this library in your work, please cite the paper first introducing these capabilities:

Bussemaker, J.H. et al., 2026, April.
System Architecture Optimization Using SysML v2: Language Extension and Implementation.
IEEE SysCon 2026, Halifax, Canada.
doi: [10.1109/SysCon66367.2026.11503593](https://dx.doi.org/10.1109/SysCon66367.2026.11503593)

## Contributing

The project is coordinated by: Jasper Bussemaker (*jasper.bussemaker at dlr.de*)

If you find a bug or have a feature request, please file an issue using the Github issue tracker.
If you require support for using the library or want to collaborate, feel free to contact me.

Contributions are appreciated too:
- Fork the repository
- Add your contributions to the fork
  - Update/add documentation
  - Add tests and make sure they pass (tests are run using `pytest`)
- Read and sign a Contributor License Agreement (CLA): *please contact me for the template*
- Issue a pull request
