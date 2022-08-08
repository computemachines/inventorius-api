import * as React from "react";

import "../styles/PropertiesTable.css"
import AutocompleteInput from "./Autocomplete";

// export type PropertyType = "string" | "date" | "integer" | "float" | "currency" | "physical-unit";
// export type PropertyType = "string";

export interface Currency {
    value: number,
    monetaryUnit: string,
}
export class USD implements Currency {
    value: number;
    monetaryUnit: "USD";
    constructor(value: number) {
        this.value = value;
    }
}

export interface Property {
    name: string;
    typed: {
        kind: "string";
        value: string;
    } | {
        kind: "currency";
        value: Currency;
    };
}

const defaultProperties: Property[] = [
    { name: "", typed: { kind: "string", value: "" } }];

const suggestProperties: Property[] = [
    { name: "Cost of Raw Goods", typed: { kind: "currency", value: new USD(0)}}
]

function PropertyRow(
    { property }: {
        property: Property;
        // setProperty: (property) => void;
    }) {
    return <div className="property-row">
        <div className="property-name">{property.name}</div>
        <div className="property-value">{property.typed.value}</div>
    </div>;
}

function EditablePropertyInputRow(
    { property, setProperty }: {
        property: Property;
        setProperty: (property) => void;
    }) {
    let valueInput;
    switch (property.typed.kind) {
        case "string": valueInput = <input
            type="text"
            id={"property_" + property.name}
            value={property.typed.value}
            onChange={(e) => {
                let newTyped = { ...property.typed };
                newTyped.value = e.target.value;
                setProperty({ ...property, typed: newTyped });
            }} />
    }

    return <div className="property-row">
        <AutocompleteInput
            value={property.name}
            onChange={(e) => {
                setProperty({ ...property, name: e.target.value });
            }}
        />
        <input
            type="text"
            placeholder="property type"
        />
        {valueInput}
    </div>;
}

function PropertiesTable(
    { properties, setProperties, editable }: {
        properties: Property[];
        setProperties: (properties: Property[]) => void;
        editable: boolean
    }) {

    if (editable) {
        return <div className="properties-table">
            {(properties.length == 0 ? defaultProperties : properties).map((property, i, visibleProperties) => (
                <EditablePropertyInputRow property={property} setProperty={(newProperty) => {
                    const newProperties = [...visibleProperties];
                    newProperties[i] = newProperty;
                    console.log("set properties");
                    setProperties(newProperties);
                }} />
            ))}
        </div>;
    } else {
        return <div className="properties-table">
            {properties.map((property, i, properties) => (
                <PropertyRow key={i} property={property} />))
            }
        </div>;
    }
}

export default PropertiesTable;