import * as React from "react";

import "../styles/DataTable.css";
import ItemLabel from "./ItemLabel";

type DataTableType = "string" | "boolean" | "ItemLabel" | "number";

function DataCell({ value, type }: { value: unknown; type?: DataTableType }) {
  let cell = value;
  if (type == "ItemLabel") cell = <ItemLabel label={value as string} />;
  return <td>{cell}</td>;
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
        <thead>
          <tr>
            {headers.map((value, index) => (
              <th key={"th-" + index}>{value}</th>
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
