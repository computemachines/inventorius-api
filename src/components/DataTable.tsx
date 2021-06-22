import * as React from "react";
import { useRef } from "react";

import "../styles/DataTable.css";
import ItemLabel from "./ItemLabel";

type WidthSpec = FixedWidth | MinMaxWidth;
interface FixedWidth {
  kind: "fixed-width";
  width: number | string;
}
interface MinMaxWidth {
  kind: "min-max-width";
  minWidth: number | string;
  maxWidth: number | string;
}

export class HeaderSpec {
  constructor(
    public headerType?: DataTableType,
    public width: WidthSpec = {
      kind: "fixed-width",
      width: "auto",
    }
  ) {}
}

type DataTableType =
  | "string"
  | "boolean"
  | ".ItemLabel"
  | ".numeric"
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
  className,
  children,
  onResize,
}: {
  className?: string;
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

  const mouseMoveListener = (e) =>
    requestAnimationFrame((time) => {
      // console.log("window#mousemove");
      const width =
        document.documentElement.scrollLeft +
        e.clientX -
        headerElement.current.offsetLeft;
      onResize(width);
    });

  return (
    <th ref={headerElement} scope="col" className={className}>
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
  loading,
}: {
  headers: string[];
  data: Record<string, unknown>[];
  headerSpecs: Record<string, HeaderSpec>;
  loading?: boolean;
}) {
  const [columnSizes, setColumnSizes] = React.useState(
    headers.map((header) => {
      const width: WidthSpec = (headerSpecs[header] || new HeaderSpec()).width;
      switch (width.kind) {
        case "min-max-width":
          return `minmax(${width.minWidth}px, ${width.maxWidth})`;
        case "fixed-width":
          return typeof width.width == "string"
            ? width.width
            : `${width.width}px`;
        default:
          const _: never = width;
      }
    })
  );

  return (
    <div className={`data-table-container ${loading ? "loading" : ""}`}>
      <table
        className="data-table"
        style={{ gridTemplateColumns: columnSizes.join(" ") }}
      >
        <colgroup>
          {headers.map((header, index) => (
            <col
              key={"col-" + index}
              className={
                headerSpecs[header]?.headerType.startsWith(".")
                  ? headerSpecs[header].headerType.slice(1)
                  : ""
              }
            />
          ))}
        </colgroup>
        <thead>
          <tr>
            {headers.map((header, index) => (
              <ResizableHeader
                resizable={
                  index != headers.length - 1 &&
                  headerSpecs[header]?.width.kind == "min-max-width"
                }
                className={
                  headerSpecs[header]?.headerType.startsWith(".")
                    ? headerSpecs[header].headerType.slice(1)
                    : ""
                }
                key={"th-" + index}
                onResize={(width) => {
                  const newColumnSizes = [...columnSizes];
                  let widthSpec = headerSpecs[header]?.width;
                  if (widthSpec?.kind == "min-max-width") {
                    if (typeof widthSpec.minWidth == "number")
                      width = Math.max(width, widthSpec.minWidth);
                    if (typeof widthSpec.maxWidth == "number")
                      width = Math.min(width, widthSpec.maxWidth);
                  }
                  newColumnSizes[index] = `${width}px`;
                  setColumnSizes(newColumnSizes);
                }}
              >
                {header}
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
