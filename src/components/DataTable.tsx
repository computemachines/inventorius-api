import * as React from "react";
import { useRef } from "react";

import "../styles/DataTable.css";
import ItemLabel from "./ItemLabel";

export class HeaderSpec {
  constructor(
    public headerType: DataTableType,
    public minWidth: number = 50,
    public maxWidth: string = "1fr"
  ) {}
}

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
  onResize,
}: {
  resizable?: boolean;
  children: React.ReactNode;
  onResize?: (width: number) => void;
}) {
  let headerElement = useRef(null);

  const mouseUpListener = () => {
    // console.log("window#mouseup");
    window.removeEventListener("mousemove", mouseMoveListener);
    window.removeEventListener("mouseup", mouseUpListener);
  };

  const mouseMoveListener = (e) => {
    // console.log("window#mousemove");
    const width =
      document.documentElement.scrollLeft +
      e.clientX -
      headerElement.current.offsetLeft;
    onResize(width);
  };

  return (
    <th ref={headerElement} scope="col">
      {children}
      {resizable && (
        <span
          onMouseDown={() => {
            // console.log("span#mousedown");
            window.addEventListener("mouseup", mouseUpListener);
            window.addEventListener("mousemove", mouseMoveListener);
          }}
          className="resize-handle"
        />
      )}
    </th>
  );
}

function DataTable({
  headers,
  data,
  headerSpecs,
}: {
  headers: string[];
  data: Record<string, unknown>[];
  headerSpecs: Record<string, HeaderSpec>;
}) {
  const [columnSizes, setColumnSizes] = React.useState(
    headers.map((header) =>
      headerSpecs[header]
        ? `minmax(${headerSpecs[header].minWidth}px, ${headerSpecs[header].maxWidth})`
        : "minmax(50px, 1fr)"
    )
  );

  return (
    <div className="data-table-container">
      <table
        className="data-table"
        style={{ gridTemplateColumns: columnSizes.join(" ") }}
      >
        <colgroup>
          {headers.map((value, index) => (
            <col
              key={"col-" + index}
              className={
                headerSpecs[value]?.headerType.startsWith(".")
                  ? headerSpecs[value].headerType.slice(1)
                  : ""
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
                onResize={(width) => {
                  const newColumnSizes = [...columnSizes];
                  newColumnSizes[index] = `${width}px`;
                  setColumnSizes(newColumnSizes);
                }}
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
                  type={headerSpecs[key]?.headerType}
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
