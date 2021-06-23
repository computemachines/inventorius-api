import * as React from "react";
import { useContext, useState } from "react";
import { useFrontload } from "react-frontload";
import { FrontloadContext } from "../api-client/inventory-api";

import "../styles/form.css";
import { AlertContext } from "./Alert";
import CodesInput from "./CodesInput";
import PrintButton from "./PrintButton";

function NewSku() {
  const { data, frontloadMeta } = useFrontload(
    "new-sku-component",
    async ({ api }: FrontloadContext) => ({
      api: api,
      nextSku: await api.getNextSku(),
    })
  );
  const { setAlertContent } = useContext(AlertContext);
  const [skuIdValue, setSkuIdValue] = useState("");
  const [nameValue, setNameValue] = useState("");
  const [codes, setCodes] = useState([""]);

  let skuIdPlaceholder;
  if (frontloadMeta.pending) skuIdPlaceholder = "Loading...";
  else if (frontloadMeta.error || data.nextSku.kind == "problem")
    skuIdPlaceholder = "API Error";
  else skuIdPlaceholder = data.nextSku.state;

  return (
    <form className="form">
      <h2 className="form-title">New Sku</h2>
      <label htmlFor="sku_id" className="form-label">
        Sku Label
      </label>
      <div className="flex-row">
        <input
          type="text"
          name="sku_id"
          id="sku_id"
          placeholder={skuIdPlaceholder}
          className="form-single-code-input"
          value={skuIdValue}
          onChange={(e) => setSkuIdValue(e.target.value)}
        />
        <PrintButton value={skuIdValue || skuIdPlaceholder} />
      </div>
      <label htmlFor="name" className="form-label">
        Name
      </label>
      <input
        type="text"
        name="name"
        id="name"
        className="form-single-code-input"
        value={nameValue}
        onChange={(e) => setNameValue(e.target.value)}
      />
      <label htmlFor="codes" className="form-label">
        Codes
      </label>
      <CodesInput id="codes" codes={codes} setCodes={setCodes} />
      <input type="submit" value="Submit" className="form-submit" />
    </form>
  );
}
export default NewSku;
