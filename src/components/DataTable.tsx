import * as React from "react";

import "../styles/DataTable.css";
import ItemLabel from "./ItemLabel";

type DataTableType =
  | "string"
  | "boolean"
  | ".ItemLabel"
  | "number"
  | ".truncated";

function DataCell({ value, type }: { value: unknown; type?: DataTableType }) {
  switch (type) {
    case ".ItemLabel":
      return (
        <td>
          <ItemLabel label={value as string} />
        </td>
      );
      break;

    case ".truncated":
      return <td className="truncated">{value}</td>;
      break;

    default:
      return <td>{value}</td>;
      break;
  }
}

function ResizableHeader({
  resizable = true,
  children,
}: {
  resizable?: boolean;
  children: React.ReactNode;
}) {
  return (
    <th scope="col">
      {children} {resizable && <span className="resize-handle" />}
    </th>
  );
}

function DataTable({
  headers,
  data,
  types,
}: {
  headers: string[];
  data: Record<string, unknown>[];
  types: Record<string, DataTableType>;
}) {
  return (
    <div className="data-table-container">
      <table className="data-table">
        <colgroup>
          {headers.map((value, index) => (
            <col
              key={"col-" + index}
              className={
                types[value]?.startsWith(".") ? types[value].slice(1) : ""
              }
            />
          ))}
        </colgroup>
        <thead>
          <tr>
            {headers.map((value, index) => (
              <ResizableHeader
                resizable={index != headers.length - 1}
                key={"th-" + index}
              >
                {value}
              </ResizableHeader>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, row_index) => (
            <tr key={"tr-" + row_index}>
              {headers.map((key, col_index) => (
                <DataCell
                  key={"td-" + col_index}
                  value={row[key]}
                  type={types[key]}
                />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export default DataTable;
