import * as React from "react";
import { Currency, Props, Unit1, USD } from "../api-client/data-models";
import { CrossCircle } from "../img/lnr";
import PlusCircle from "../img/lnr/PlusCircle";

import "../styles/PropertiesTable.css";
import AutocompleteInput from "./Autocomplete";

// export type PropertyType = "string" | "date" | "integer" | "float" | "currency" | "physical-unit";
// export type PropertyType = "string";

const PropertyTypes: string[] = ["string", "currency", "number"];

function defaultPropertyType(
  type: "string" | "currency" | "number"
): string | Currency | number {
  switch (type) {
    case "currency":
      return new USD(0);
      break;
    case "number":
      return 0;
      break;
    case "string":
      return "";
      break;
    default:
      throw new Error("Impossible fallthrough");
  }
}

export class Property {
  name: string;
  typed:
    | {
        kind: "string";
        value: string;
      }
    | {
        kind: "currency";
        value: Currency;
      }
    | {
        kind: "number";
        value: number;
      };
  constructor({ name, typed }) {
    this.name = name;
    this.typed = typed;
  }
  value(): string | number | Unit1 {
    switch (this.typed.kind) {
      case "currency":
        return this.typed.value;
      case "number":
        return this.typed.value;
      case "string":
        return this.typed.value;
    }
  }
}

export function api_props_from_properties(properties: Property[]): Props {
  let ret = {};
  for (let i = 0; i < properties.length; i++) {
    ret[properties[i].name] = new Property(properties[i]).value();
  }
  return ret;
}

const defaultProperty: Property = new Property({
  name: "",
  typed: {
    kind: "string",
    value: "",
  },
});

const predefinedProperties: Property[] = [
  new Property({
    name: "original_cost_per_case",
    typed: {
      kind: "currency",
      value: new USD(0),
    },
  }),
  new Property({
    name: "original_count_per_case",
    typed: { kind: "number", value: 1 },
  }),
];

function PropertyRow({
  property,
}: {
  property: Property;
  // setProperty: (property) => void;
}) {
  return (
    <>
      <div className="properties-table__name">{property.name}</div>
      <div className="properties-table__value">{property.typed.value}</div>
    </>
  );
}

function EditablePropertyInputRow({
  property,
  setProperty,
  insertProperty,
  deleteProperty,
  isLast,
}: {
  property: Property;
  setProperty: (property) => void;
  insertProperty: () => void;
  deleteProperty: () => void;
  isLast: boolean;
}) {
  const commonProps = {
    onChange(e) {
      let newTyped = { ...property.typed };
      newTyped.value = e.target.value;
      setProperty({ ...property, typed: newTyped });
    },
    onKeyDown(e) {
      if (e.key == "Tab" && property.name) {
        insertProperty();
      }
    },
    id: "property_" + property.name,
    name: "property_" + property.name,
  };
  if (!isLast) {
    delete commonProps.onKeyDown;
  }

  let valueInput;
  switch (property.typed.kind) {
    case "string":
      valueInput = (
        <input type="text" {...commonProps} value={property.typed.value} />
      );
      break;
    case "currency":
      valueInput = (
        <input
          type="number"
          value={property.typed.value.value}
          {...commonProps}
          onChange={(e) =>
            setProperty({
              ...property,
              typed: {
                kind: "currency",
                value: new USD(parseFloat(e.target.value)),
              },
            })
          }
        />
      );
      break;
    case "number":
      valueInput = (
        <input type="number" {...commonProps} value={property.typed.value} />
      );
      break;
    default:
      throw new Error("Impossible fallthrough");
  }

  return (
    <div className="properties-table-row">
      <AutocompleteInput
        className="properties-table-row__name"
        value={property.name}
        setValue={(name) => {
          let predefined = predefinedProperties.find(
            (predefinedProperty) => name == predefinedProperty.name
          );
          if (typeof predefined !== "undefined") {
            setProperty({ ...predefined });
          } else {
            setProperty({ ...property, name });
          }
        }}
        suggestions={predefinedProperties.map((property) => property.name)}
      />
      <select
        className="properties-table-row__type"
        disabled={predefinedProperties.some(
          (predefinedProperty) => predefinedProperty.name == property.name
        )}
        value={property.typed.kind}
        onChange={(e) =>
          setProperty({
            ...property,
            typed: {
              kind: e.target.value,
              value: defaultPropertyType(
                e.target.value as "number" | "string" | "currency"
              ),
            },
          })
        }
      >
        {PropertyTypes.map((type, i) => (
          <option key={i} value={type}>
            {type}
          </option>
        ))}
      </select>
      <div className="properties-table-row__value">{valueInput}</div>
      {isLast ? (
        <PlusCircle
          className="lnr-plus-circle properties-table-row__button"
          onClick={(e) => insertProperty()}
        />
      ) : (
        <CrossCircle
          className="lnr-cross-circle properties-table-row__button"
          onClick={(e) => deleteProperty()}
        />
      )}
    </div>
  );
}

function PropertiesTable({
  properties,
  setProperties,
  editable,
}: {
  properties: Property[];
  setProperties: (properties: Property[]) => void;
  editable: boolean;
}) {
  return (
    <div
      className={`properties-table ${
        editable ? "properties-table--editing" : ""
      }`}
    >
      {editable
        ? (properties.length == 0 ? [defaultProperty] : properties).map(
            (property, i, visibleProperties) => (
              <EditablePropertyInputRow
                key={i}
                property={property}
                setProperty={(newProperty) => {
                  let newProperties = [...visibleProperties];
                  newProperties[i] = newProperty;
                  setProperties(newProperties);
                }}
                insertProperty={() => {
                  setProperties([...properties, defaultProperty]);
                }}
                deleteProperty={() => {
                  let newProperties = [...visibleProperties];
                  newProperties.splice(i, 1);
                  setProperties(newProperties);
                }}
                isLast={i == visibleProperties.length - 1}
              />
            )
          )
        : properties.map((property, i, properties) => (
            <PropertyRow key={i} property={property} />
          ))}
    </div>
  );
}

export default PropertiesTable;
