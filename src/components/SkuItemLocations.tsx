import * as React from "react";
import { useState } from "react";
import { useFrontload } from "react-frontload";
import { FrontloadContext } from "../api-client/inventory-api";

import "../styles/SkuItemLocations.css";
import DataTable, { HeaderSpec } from "./DataTable";
import { Sku as APISku } from "../api-client/data-models";

function SkuItemLocations({ key = "", sku }: { key?: string; sku?: APISku }) {
  const [tabularData, setTabularData] = useState(
    [] as {
      Bin: string;
      Identifier: string;
      Type: string;
      Quantity: number;
    }[]
  );
  const [isProblem, setProblem] = useState(false);

  React.useEffect(() => {
    let myTabularData = [];
    sku?.bins().then((value) => {
      if (value.kind == "problem") return setProblem(true);
      for (const binId in value.state) {
        for (const itemId in value.state[binId]) {
          myTabularData.push({
            Bin: binId,
            Identifier: itemId,
            Quantity: value.state[binId][itemId],
          });
        }
      }
      setTabularData(myTabularData);
    });
  }, [sku]);

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
