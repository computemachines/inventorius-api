import * as React from "react";
import { useState } from "react";
import { FrontloadContext } from "../api-client/api-client";

import "../styles/ItemLocations.css";
import DataTable, { HeaderSpec } from "./DataTable";
import {
  BatchLocations,
  Sku as APISku,
  SkuLocations,
} from "../api-client/data-models";

function ItemLocations({
  key = "",
  itemLocations: itemLocations,
}: {
  key?: string;
  itemLocations: SkuLocations | BatchLocations;
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
    const myTabularData = [];
    // if (sku?.kind == "problem") return;
    for (const binId in itemLocations.state) {
      for (const itemId in itemLocations.state[binId]) {
        myTabularData.push({
          Bin: binId,
          Identifier: itemId,
          Quantity: itemLocations.state[binId][itemId],
        });
      }
    }
    setTabularData(myTabularData);
  }, [itemLocations]);

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
export default ItemLocations;
