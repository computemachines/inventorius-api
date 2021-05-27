import * as React from "react";
import { useParams } from "react-router-dom";

import "../styles/infoPanel.css";
import FilterWidget from "./FilterWidget";

import ItemLabel from "./ItemLabel";
import PrintButton from "./PrintButton";

function Bin() {
  const { id } = useParams();

  return (
    <div className="info-panel">
      <div className="info-item">
        <div className="info-item-title">Bin Label</div>
        <div className="info-item-description">
          <ItemLabel link={false} label={id} />
          <PrintButton />
        </div>
      </div>
      <div className="info-item">
        <div className="info-item-title">
          Contents
          <FilterWidget />
        </div>
        <div className="info-item-description"></div>
      </div>
    </div>
  );
}

export default Bin;
