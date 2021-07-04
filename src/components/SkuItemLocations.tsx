import * as React from "react";
import { useState } from "react";
import { FrontloadContext } from "../api-client/inventory-api";

import "../styles/SkuItemLocations.css";
import DataTable, { HeaderSpec } from "./DataTable";
import { Sku as APISku, SkuLocations } from "../api-client/data-models";

function SkuItemLocations({
  key = "",
  sku_bins,
}: {
  key?: string;
  sku_bins: SkuLocations;
}) {
  const [tabularData, setTabularData] = useState<
    Array<{
      Bin: string;
      Identifier: string;
      Type: string;
      Quantity: number;
    }>
  >([]);
  // const [isProblem, setProblem] = useState(false);

  React.useEffect(() => {
    let myTabularData = [];
    // if (sku?.kind == "problem") return;
    for (const binId in sku_bins.state) {
      for (const itemId in sku_bins.state[binId]) {
        myTabularData.push({
          Bin: binId,
          Identifier: itemId,
          Quantity: sku_bins.state[binId][itemId],
        });
      }
    }
    setTabularData(myTabularData);
  }, [sku_bins]);

  return (
    <DataTable
      headers={["Bin", "Identifier", "Quantity", "Type"]}
      data={tabularData}
      headerSpecs={{
        Bin: new HeaderSpec(".ItemLabel"),
        Identifier: new HeaderSpec(".ItemLabel"),
        Quantity: new HeaderSpec(".numeric"),
      }}
    />
  );
}
export default SkuItemLocations;
