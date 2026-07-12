# SysML v2 Python Units

Convert units and quantities between standard [SysML v2](https://www.omg.org/sysml/sysmlv2/) and Python with
[Syside Automator](https://docs.sensmetry.com/automator/) and [Pint](https://pint.readthedocs.io/).

- Get/set quantity* as `attribute` value, specified using Pint `Quantity` objects
- Get/set unit as `attribute` value, specified using Pint `Unit` objects
- Supports numerical values/magnitudes, as well as `inf` (`*` in SysML v2) and `NaN` (set as `null` in SysML v2)
- Conversion functions between SysML v2 units and Pint `Unit`, and string parsing functions
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
