import * as React from "react";
import { useFrontload } from "react-frontload";
import { useParams } from "react-router-dom";
import * as Sentry from "@sentry/react";

import { FrontloadContext } from "../api-client/api-client";

import "../styles/infoPanel.css";
import DataTable, { HeaderSpec } from "./DataTable";
import FilterWidget from "./FilterWidget";
import { FourOhFour } from "./FourOhFour";

import ItemLabel from "./ItemLabel";
import PrintButton from "./PrintButton";
import { Batch, Problem, Sku } from "../api-client/data-models";
import * as e from "express";

function BinContentsTable({
  key = "",
  contents,
  filterShow = "all",
}: {
  key?: string;
  contents: Record<string, number>;
  filterShow?: "sku" | "bat" | "all";
}) {
  const { data, frontloadMeta } = useFrontload(
    `bin-contents-table-${key}-component`,
    async ({ api }: FrontloadContext) => ({
      detailedContents: await Promise.all(
        Object.entries(contents).map(async function ([id, quantity]) {
          let item: Problem | Sku | Batch;
          if (id.startsWith("SKU")) {
            item = await api.getSku(id);
          } else if (id.startsWith("BAT")) {
            item = await api.getBatch(id);
          } else {
            Sentry.captureException(
              "Bad id provided to bindcontentstable(contents)"
            );
          }
          if (item.kind == "problem")
            return { id, quantity, kind: "problem", problem: item };
          else return { id, quantity, kind: item.kind, item: item };
        })
      ),
    })
  );
  if (frontloadMeta.error) {
    Sentry.captureException(new Error("API Error"));
    return <span>API Error</span>;
  }

  let tabularData: {
    Identifier: string;
    Name: string;
    Quantity: number;
    Type: string;
  }[];

  if (frontloadMeta.done) {
    tabularData = data.detailedContents.map((row) => {
      if (row.kind == "problem") {
        Sentry.captureException(new Error("bin contents table bad row"));
      }
      return {
        Identifier: row.id,
        Quantity: row.quantity,
        Type: row.kind,
        Name: row.kind != "problem" ? row.item.state.name : null,
      };
    });
  } else {
    tabularData = Object.entries(contents).map(([Identifier, Quantity]) => ({
      Identifier,
      Quantity,
      Type: "Loading",
      Name: "Loading",
    }));
  }

  return (
    <DataTable
      headers={["Identifier", "Name", "Quantity", "Type"]}
      data={tabularData}
      headerSpecs={{
        Identifier: new HeaderSpec(".ItemLabel"),
        Name: new HeaderSpec(".truncated", {
          kind: "min-max-width",
          minWidth: 100,
          maxWidth: "1fr",
        }),
        Quantity: new HeaderSpec(".numeric"),
      }}
    />
  );
}
function Bin(): JSX.Element {
  const { id } = useParams<{ id: string }>();
  const { data, frontloadMeta } = useFrontload(
    "bin-component",
    async ({ api }: FrontloadContext) => ({
      bin: await api.getBin(id),
    })
  );
  if (frontloadMeta.done && data.bin.kind == "problem") {
    if (data.bin.type == "missing-resource") return <FourOhFour />;
    else return <h2>{data.bin.title}</h2>;
  }

  if (frontloadMeta.error) {
    return <div>Connection Error</div>;
  }

  return (
    <div className="info-panel">
      <div className="info-item">
        <div className="info-item-title">Bin Label</div>
        <div className="info-item-description">
          <ItemLabel link={false} label={id} />
          <PrintButton value={id} />
        </div>
      </div>
      <div className="info-item">
        <div className="info-item-title">
          Contents
          <FilterWidget />
        </div>
        <div className="info-item-description">
          {/* <DataTable>
            <DataTableHeaders>
              <Header></Header>
            </DataTableHeaders>
            <DataTableRow>

            </DataTableRow>
          </DataTable> */}
          {frontloadMeta.done && data.bin.kind != "problem" ? (
            <BinContentsTable key={id} contents={data.bin.state.contents} />
          ) : null}
        </div>
      </div>
    </div>
  );
}

export default Bin;
