import * as React from "react";
import { useContext, useEffect, useState } from "react";

import { ApiContext } from "../api-client/inventory-api";
import { AlertContext } from "./Alert";

import "../styles/form.css";
import { json } from "express";
import ItemLabel from "./ItemLabel";
import { parse, stringifyUrl } from "query-string";
import { generatePath, useHistory, useLocation } from "react-router-dom";
// import "../styles/Receive.css"

function Receive() {
  const location = useLocation();
  const history = useHistory();
  const api = useContext(ApiContext);
  const { setAlertContent } = useContext(AlertContext);

  const [intoIdValue, setIntoIdValue] = useState("");
  const [itemIdValue, setItemIdValue] = useState("");
  const [quantityValue, setQuantityValue] = useState("1");

  useEffect(() => {
    const queryParams = parse(location.search);
    if (queryParams["into"]) {
      setIntoIdValue(queryParams["into"] as string);
    }
    if (queryParams["item"]) {
      setItemIdValue(queryParams["item"] as string);
    }
    if (queryParams["quantity"]) {
      setQuantityValue(queryParams["quantity"] as string);
    }
  }, [location.search]);

  return (
    <form
      className="form"
      onSubmit={async (e) => {
        e.preventDefault();

        const resp = await api.receive({
          into_id: intoIdValue,
          item_id: itemIdValue,
          quantity: parseInt(quantityValue),
        });
        if (resp.kind == "ok") {
          setAlertContent({
            content: (
              <div>
                Success. {quantityValue} count{" "}
                <ItemLabel
                  url={itemIdValue}
                  onClick={(e) => setAlertContent({})}
                />
                , added to{" "}
                <ItemLabel
                  url={intoIdValue}
                  onClick={(e) => setAlertContent({})}
                />
              </div>
            ),
            mode: "success",
          });
          setItemIdValue("");
          setIntoIdValue("");
          setQuantityValue("1");
          if (location.search) history.push("/receive");
        } else {
          setAlertContent({
            content: <div>{resp.title}</div>,
            mode: "failure",
          });
        }
      }}
    >
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
