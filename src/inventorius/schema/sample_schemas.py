"""Sample schemas for testing and production use."""

from .trigger_engine import (
    Schema,
    Mixin,
    SchemaField,
    ChildMixin,
    TriggerCondition,
    IntersectionRule,
)


# =============================================================================
# SKU Schema - Item types with dynamic attributes
# =============================================================================

def get_sku_schema() -> Schema:
    """
    Build the SKU schema for inventory items.

    Structure:
    - Root: ItemTypeSelector (text field for item type)
    - Item type triggers component-specific mixins (Resistor, Capacitor, etc.)
    - Component mixins trigger ElectronicPackage when relevant fields are set
    - Package selection triggers SMD or ThroughHole mixins
    - Intersections add fields for specific combinations
    """

    # Shared field definitions
    package = SchemaField("package", "enum", options=[
        "0201", "0402", "0603", "0805", "1206",  # SMD
        "DIP", "TO-220", "TO-92", "SIP"  # Through-hole
    ])

    # Root mixin - always present, provides item_type field
    item_type_selector = Mixin(
        name="ItemTypeSelector",
        fields=[
            SchemaField("item_type", "text"),  # Will be typeahead eventually
        ],
        children=[
            ChildMixin("Resistor", TriggerCondition("item_type", "eq", "Resistor")),
            ChildMixin("Capacitor", TriggerCondition("item_type", "eq", "Capacitor")),
            ChildMixin("Resonator", TriggerCondition("item_type", "eq", "Resonator")),
            ChildMixin("Resin", TriggerCondition("item_type", "eq", "Resin")),
        ]
    )

    # Component type mixins
    resistor = Mixin(
        name="Resistor",
        fields=[
            SchemaField("resistance", "unit", unit="Ω"),
            SchemaField("tolerance", "enum", options=["1%", "5%", "10%"]),
        ],
        children=[
            ChildMixin("ElectronicPackage", TriggerCondition("resistance", "set", True))
        ]
    )

    capacitor = Mixin(
        name="Capacitor",
        fields=[
            SchemaField("capacitance", "unit", unit="F"),
            SchemaField("voltage_rating", "unit", unit="V"),
        ],
        children=[
            ChildMixin("ElectronicPackage", TriggerCondition("capacitance", "set", True))
        ]
    )

    resonator = Mixin(
        name="Resonator",
        fields=[
            SchemaField("frequency", "unit", unit="Hz"),
            SchemaField("load_capacitance", "unit", unit="pF"),
        ],
        children=[
            ChildMixin("ElectronicPackage", TriggerCondition("frequency", "set", True))
        ]
    )

    resin = Mixin(
        name="Resin",
        fields=[
            SchemaField("resin_type", "enum", options=["UV", "Epoxy", "Polyurethane"]),
            SchemaField("volume", "unit", unit="mL"),
        ],
        children=[]  # Resin doesn't have package selection
    )

    # Package selection mixin
    electronic_package = Mixin(
        name="ElectronicPackage",
        fields=[package],
        children=[
            ChildMixin("SMD", TriggerCondition("package", "in",
                ["0201", "0402", "0603", "0805", "1206"])),
            ChildMixin("ThroughHole", TriggerCondition("package", "in",
                ["DIP", "TO-220", "TO-92", "SIP"])),
        ]
    )

    smd = Mixin(name="SMD", fields=[], children=[])

    through_hole = Mixin(
        name="ThroughHole",
        fields=[
            SchemaField("wire_gauge", "number"),
        ],
        children=[
            ChildMixin("HighCurrentWire", TriggerCondition("wire_gauge", "lt", 20))
        ]
    )

    high_current = Mixin(
        name="HighCurrentWire",
        fields=[
            SchemaField("material", "enum", options=["copper", "nichrome", "kanthal"]),
        ],
        children=[]
    )

    # Intersection rules - fields added for specific combinations
    intersections = [
        IntersectionRule(
            when=["Resistor", "SMD"],
            adds=[SchemaField("temp_coefficient", "unit", unit="ppm/°C")]
        ),
        IntersectionRule(
            when=["Capacitor", "SMD"],
            adds=[SchemaField("dielectric_type", "enum", options=["C0G", "X7R", "Y5V"])]
        ),
        IntersectionRule(
            when=["Resonator", "SMD"],
            adds=[SchemaField("frequency_stability", "unit", unit="ppm")]
        ),
    ]

    return Schema(
        root_mixins=["ItemTypeSelector"],
        mixins={
            "ItemTypeSelector": item_type_selector,
            "Resistor": resistor,
            "Capacitor": capacitor,
            "Resonator": resonator,
            "Resin": resin,
            "ElectronicPackage": electronic_package,
            "SMD": smd,
            "ThroughHole": through_hole,
            "HighCurrentWire": high_current,
        },
        intersections=intersections,
    )


# =============================================================================
# Batch Schema - Provenance/source tracking
# =============================================================================

def get_batch_schema() -> Schema:
    """
    Build the Batch schema for tracking item provenance.

    Structure:
    - Root: SourceSelector (text field for source/supplier)
    - Source triggers supplier-specific mixins (DigiKey, Amazon, etc.)
    - Each supplier has its own tracking fields
    """

    # Root mixin - always present, provides source field
    source_selector = Mixin(
        name="SourceSelector",
        fields=[
            SchemaField("source", "text"),  # Will be typeahead eventually
        ],
        children=[
            ChildMixin("DigiKey", TriggerCondition("source", "eq", "DigiKey")),
            ChildMixin("Amazon", TriggerCondition("source", "eq", "Amazon")),
            ChildMixin("eBay", TriggerCondition("source", "eq", "eBay")),
            ChildMixin("Mouser", TriggerCondition("source", "eq", "Mouser")),
            ChildMixin("LCSC", TriggerCondition("source", "eq", "LCSC")),
        ]
    )

    # Supplier-specific mixins
    digikey = Mixin(
        name="DigiKey",
        fields=[
            SchemaField("order_number", "text"),
            SchemaField("ship_date", "text"),  # Could be date type
            SchemaField("cost_per_unit", "unit", unit="$"),
        ],
        children=[]
    )

    amazon = Mixin(
        name="Amazon",
        fields=[
            SchemaField("order_id", "text"),
            SchemaField("delivery_date", "text"),
            SchemaField("return_deadline", "text"),
        ],
        children=[]
    )

    ebay = Mixin(
        name="eBay",
        fields=[
            SchemaField("listing_id", "text"),
            SchemaField("seller_rating", "text"),
            SchemaField("condition_notes", "text"),
        ],
        children=[]
    )

    mouser = Mixin(
        name="Mouser",
        fields=[
            SchemaField("order_number", "text"),
            SchemaField("ship_date", "text"),
            SchemaField("cost_per_unit", "unit", unit="$"),
        ],
        children=[]
    )

    lcsc = Mixin(
        name="LCSC",
        fields=[
            SchemaField("order_number", "text"),
            SchemaField("ship_date", "text"),
            SchemaField("cost_per_unit", "unit", unit="$"),
            SchemaField("lcsc_part_number", "text"),
        ],
        children=[]
    )

    return Schema(
        root_mixins=["SourceSelector"],
        mixins={
            "SourceSelector": source_selector,
            "DigiKey": digikey,
            "Amazon": amazon,
            "eBay": ebay,
            "Mouser": mouser,
            "LCSC": lcsc,
        },
        intersections=[],
    )


# =============================================================================
# Demo/Test Schemas
# =============================================================================


def get_decimal_schema() -> Schema:
    """Build the pathological decimal number schema for depth testing."""

    def digit_field(n: int) -> SchemaField:
        return SchemaField(f"digit{n}", "enum", options=list("0123456789"))

    def final_field(n: int) -> SchemaField:
        return SchemaField(f"final{n}", "bool")

    mixins = {}
    for i in range(1, 6):  # Support 5 digits
        fields = [digit_field(i), final_field(i)]
        children = []
        if i < 5:
            # Trigger when final is false (user unchecks to add more digits)
            children = [
                ChildMixin(f"Digit{i+1}", TriggerCondition(f"final{i}", "eq", False))
            ]
        mixins[f"Digit{i}"] = Mixin(name=f"Digit{i}", fields=fields, children=children)

    # Add some intersection rules for fun
    intersections = [
        IntersectionRule(
            when=["Digit1", "Digit3"],
            adds=[SchemaField("three_digit_note", "text")]
        ),
        IntersectionRule(
            when=["Digit1", "Digit5"],
            adds=[SchemaField("five_digit_celebration", "enum", options=["🎉", "🎊", "🥳", "✨"])]
        ),
    ]

    return Schema(
        root_mixins=["Digit1"],
        mixins=mixins,
        intersections=intersections,
    )


def get_electronics_schema() -> Schema:
    """Build the electronics components schema."""

    # Field definitions
    resistance = SchemaField("resistance", "unit", unit="Ω")
    tolerance = SchemaField("tolerance", "enum", options=["1%", "5%", "10%"])
    package = SchemaField("package", "enum", options=[
        "0201", "0402", "0603", "0805", "1206",  # SMD
        "DIP", "TO-220", "TO-92", "SIP"  # Through-hole
    ])
    temp_coef = SchemaField("temp_coefficient", "unit", unit="ppm/°C")
    wire_gauge = SchemaField("wire_gauge", "number")
    material = SchemaField("material", "enum", options=["copper", "nichrome", "kanthal"])

    capacitance = SchemaField("capacitance", "unit", unit="F")
    voltage_rating = SchemaField("voltage_rating", "unit", unit="V")
    dielectric = SchemaField("dielectric_type", "enum", options=["C0G", "X7R", "Y5V"])

    frequency = SchemaField("frequency", "unit", unit="Hz")
    load_cap = SchemaField("load_capacitance", "unit", unit="pF")
    freq_stability = SchemaField("frequency_stability", "unit", unit="ppm")

    # Mixins
    resistor = Mixin(
        name="Resistor",
        fields=[resistance, tolerance],
        children=[
            ChildMixin("ElectronicPackage", TriggerCondition("resistance", "gte", 0))
        ]
    )

    capacitor = Mixin(
        name="Capacitor",
        fields=[capacitance, voltage_rating],
        children=[
            ChildMixin("ElectronicPackage", TriggerCondition("capacitance", "gte", 0))
        ]
    )

    resonator = Mixin(
        name="Resonator",
        fields=[frequency, load_cap],
        children=[
            ChildMixin("ElectronicPackage", TriggerCondition("frequency", "gte", 0))
        ]
    )

    electronic_package = Mixin(
        name="ElectronicPackage",
        fields=[package],
        children=[
            ChildMixin("SMD", TriggerCondition("package", "in",
                ["0201", "0402", "0603", "0805", "1206"])),
            ChildMixin("ThroughHole", TriggerCondition("package", "in",
                ["DIP", "TO-220", "TO-92", "SIP"])),
        ]
    )

    smd = Mixin(name="SMD", fields=[], children=[])

    through_hole = Mixin(
        name="ThroughHole",
        fields=[wire_gauge],
        children=[
            ChildMixin("HighCurrentWire", TriggerCondition("wire_gauge", "lt", 20))
        ]
    )

    high_current = Mixin(
        name="HighCurrentWire",
        fields=[material],
        children=[]
    )

    # Intersection rules
    intersections = [
        IntersectionRule(
            when=["Resistor", "SMD"],
            adds=[temp_coef]
        ),
        IntersectionRule(
            when=["Capacitor", "SMD"],
            adds=[dielectric]
        ),
        IntersectionRule(
            when=["Resonator", "SMD"],
            adds=[freq_stability]
        ),
    ]

    return Schema(
        root_mixins=["Resistor", "Capacitor", "Resonator"],
        mixins={
            "Resistor": resistor,
            "Capacitor": capacitor,
            "Resonator": resonator,
            "ElectronicPackage": electronic_package,
            "SMD": smd,
            "ThroughHole": through_hole,
            "HighCurrentWire": high_current,
        },
        intersections=intersections,
    )
