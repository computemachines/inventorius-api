import * as React from "react";
import { useContext, useEffect, useState } from "react";

import { ApiContext } from "../api-client/inventory-api";
import { AlertContext } from "./Alert";

import "../styles/form.css";
// import "../styles/Receive.css"

function Receive() {
  const [intoIdValue, setIntoIdValue] = useState("");
  const [itemIdValue, setItemIdValue] = useState("");
  const [quantityValue, setQuantityValue] = useState("1");

  return (
    <form className="form">
      <h2 className="form-title">Receive</h2>
      <label htmlFor="into_id" className="form-label">
        Bin Label
      </label>
      <input
        type="text"
        name="into_id"
        id="into_id"
        className="form-single-code-input"
        value={intoIdValue}
        onChange={(e) => setIntoIdValue(e.target.value)}
      />
      <label htmlFor="item_id" className="form-label">
        Item Label
      </label>
      <input
        type="text"
        name="item_id"
        id="item_id"
        className="form-single-code-input"
        value={itemIdValue}
        onChange={(e) => setItemIdValue(e.target.value)}
      />
      <label htmlFor="quantity" className="form-label">
        Quantity
      </label>
      <input
        type="number"
        name="quantity"
        id="quantity"
        className="form-single-code-input"
        value={quantityValue}
        onChange={(e) => setQuantityValue(e.target.value)}
      />

      <input type="submit" value="Submit" className="form-submit" />
    </form>
  );
}
export default Receive;
