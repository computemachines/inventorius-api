import * as React from "react";
import { useFrontload } from "react-frontload";
import { useParams } from "react-router-dom";
import { FrontloadContext } from "../api-client/inventory-api";

import "../styles/Sku.css";
import { FourOhFour } from "./FourOhFour";
import ItemLabel from "./ItemLabel";
import PrintButton from "./PrintButton";
import SkuItemLocations from "./SkuItemLocations";

function Sku() {
  const { id } = useParams<{ id: string }>();
  const { data, frontloadMeta } = useFrontload(
    "sku-component",
    async ({ api }: FrontloadContext) => ({
      sku: await api.getSku(id),
    })
  );

  if (data?.sku.kind == "problem") {
    if (data.sku.type == "missing-resource") return <FourOhFour />;
    else return <h2>{data.sku.title}</h2>;
  } else {
    if (frontloadMeta.error) {
      return <div>Connection Error</div>;
    }

    return (
      <div className="info-panel">
        <div className="info-item">
          <div className="info-item-title">Sku Label</div>
          <div className="info-item-description">
            <ItemLabel link={false} label={id} />
            <PrintButton value={id} />
          </div>
        </div>
        <div className="info-item">
          <div className="info-item-title">Name</div>
          <div className="info-item-description">
            {frontloadMeta.done ? data.sku.state.name : "Loading..."}
          </div>
        </div>
        <div className="info-item">
          <div className="info-item-title">Derived Batches</div>
          <div className="info-item-description">TODO</div>
        </div>
        <div className="info-item">
          <div className="info-item-title">Locations</div>
          <div className="info-item-description">
            <SkuItemLocations sku={data?.sku} />
          </div>
        </div>
      </div>
    );
  }
}
export default Sku;
