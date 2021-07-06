import { parse } from "query-string";
import * as React from "react";
import { useContext, useState, useRef, useEffect } from "react";
import { useFrontload } from "react-frontload";
import { useLocation } from "react-router-dom";
import { ApiContext, FrontloadContext } from "../api-client/inventory-api";

import "../styles/form.css";
// import "../styles/NewBatch.css";
import { AlertContext } from "./Alert";
import CodesInput, { Code } from "./CodesInput";
import PrintButton from "./PrintButton";

function NewBatch() {
  const location = useLocation();
  const defaultParentSkuId = parse(location.search).parent as string;
  const { data, frontloadMeta } = useFrontload(
    "new-batch-component",
    async ({ api }: FrontloadContext) => ({
      nextBatch: await api.getNextBatch(),
      parentSku: defaultParentSkuId
        ? await api.getSku(defaultParentSkuId)
        : null,
    })
  );
  const api = useContext(ApiContext);
  const { setAlertContent } = useContext(AlertContext);

  const [parentSkuId, setParentSkuId] = useState("");
  const [batchIdValue, setBatchIdValue] = useState("");
  const [nameValue, setNameValue] = useState("");
  const [codes, setCodes] = useState<Code[]>([]);
  const batchIdRef = useRef(null);

  function clearForm() {
    setParentSkuId("");
    setBatchIdValue("");
    setNameValue("");
    setCodes([]);
  }

  console.log(data);
  console.log(frontloadMeta);
  if (frontloadMeta.pending) return <div>Loading...</div>;
  if (frontloadMeta.error)
    return (
      <div>
        {frontloadMeta.error.message}
        <br />
        {frontloadMeta.error.stack}
      </div>
    );

  return (
    <form className="form">
      <h2 className="form-title">New Batch</h2>
      <label htmlFor="parent_sku_id" className="form-label">
        Parent Sku
      </label>
      <input
        type="text"
        id="parent_sku_id"
        name="parent_sku_id"
        className="form-single-code-input"
        placeholder={defaultParentSkuId}
        value={parentSkuId}
        onChange={(e) => setParentSkuId(e.target.value)}
      />
      <label htmlFor="batch_id" className="form-label">
        Batch Label
      </label>
      <div className="flex-row">
        <input
          ref={batchIdRef}
          type="text"
          className="form-single-code-input"
          id="batch_id"
          name="batch_id"
          placeholder={
            data.nextBatch.kind == "next-batch"
              ? data.nextBatch.state
              : data.nextBatch.title
          }
          value={batchIdValue}
          onChange={(e) => setBatchIdValue(e.target.value)}
        />
        <PrintButton
          value={
            batchIdValue ||
            (data.nextBatch.kind == "next-batch"
              ? data.nextBatch.state
              : data.nextBatch.title)
          }
        />
      </div>
      <label htmlFor="name" className="form-label">
        Name
      </label>
      <input
        type="text"
        className="form-single-code-input"
        id="name"
        placeholder={
          data.parentSku?.kind == "sku" ? data.parentSku.state.name : ""
        }
      ></input>
      <label className="form-label" htmlFor="codes">
        Codes
      </label>
      <CodesInput id="codes" codes={codes} setCodes={setCodes} />
      <input type="submit" value="Submit" className="form-submit" />
    </form>
  );
}
export default NewBatch;
