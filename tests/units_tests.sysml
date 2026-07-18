package AttrUnits {
    private import ISQ::*;
    private import SI::*;
    private import USCustomaryUnits::*;
    
    attribute intNoUnits = 1;
    attribute rationalNoUnits = 1.0;

    attribute mass1 = 1[kg];
    attribute mass2 = 1.0[kg];
    attribute mass3 = 1.0[kilogram];

    attribute massFlow = 1.5['kg⋅s⁻¹'];

    attribute speedDef = 1['m/s'];
    attribute speedAdhoc = 1[m/s];
    attribute speedKph = 1.0['km/h'];

    attribute pressureUS = 100[psi];
    attribute pressureSI = 100[Pa];
    attribute pressureAdhoc = 100[N/m^2];

    attribute tempShort = 100['°C_abs'];
    attribute tempDeltaShort = 100['°C'];
    attribute tempLong = 100['degree celsius (absolute temperature scale)'];

    attribute btuAttr = 10['Btu_60°F'];

    attribute negativeValNoUnits = -5;
    attribute negativeVal = -5[kg];
    
    attribute adhocQual = 5[SI::kg/SI::s];
    attribute adhocQualLong = -5[SI::'kilogram' * SI::'metre per second'];
    attribute adhocQualPower = 10.0[SI::m/(SI::s^2)];

    attribute infValueNoUnit = *; // inf
    attribute nanValueNoUnit = null; // NaN
    attribute infValue = *[kg];
    attribute nanValue = null[kg];

    attribute wrappedNegativeValue = (-15)[m];

    attribute units = SI::kg;
    attribute attrRefUnits = 10[units];

    attribute aliasUnits = 50.0[NM];
    attribute units2 = NM;
    attribute aliasRefUnits = 25.0[units2];

    alias units3 for ft;
    attribute aliasRefUnits2 = 26.0[units3];

    attribute units4 subsets m;
    attribute subsetUnits = 30.0[units4];

    attribute adhocUnits = m/s;
    attribute adhocValue = 22[adhocUnits];

    attribute massValue : ISQ::MassValue;
    attribute speedValue :> ISQ::speed;
    attribute soundValue :> ISQ::soundPressureLevel;

    attribute assignedMassValue :> ISQ::mass = 100[SI::gram];

    attribute adhocComplexUnits = K*kg*s**2/m**3;
    attribute adhocComplexQuantity = 3.14 [K*kg*s**2/m**3];

    attribute energyUsage = 1 [kW*h];
    attribute energyPrefix = 1 [kilo*W*h];
}
