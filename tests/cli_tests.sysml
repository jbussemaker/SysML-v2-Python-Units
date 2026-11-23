package CLITesting {

    part def PartDef :> NotFoundPartDef {

    }

    attribute attr1 :> unknownAttr;

    attribute attr2 :> ISQ::mass;

    attribute attr3 :> ISQ::speed = 3.14 [SI::'m/s'];

    attribute attr4;

    attribute attr5 = SI::kg;

    attribute attr6 = 3.14;

}
