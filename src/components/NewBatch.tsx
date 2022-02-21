import { parse, stringifyUrl } from "query-string";
import * as React from "react";
import { useContext, useState, useRef, useEffect } from "react";
import { useFrontload } from "react-frontload";
import { useHistory, useLocation } from "react-router-dom";
import { ApiContext, FrontloadContext } from "../api-client/api-client";

import "../styles/form.css";
// import "../styles/NewBatch.css";
import { AlertContext } from "./Alert";
import CodesInput, { Code } from "./CodesInput";
import ItemLabel from "./ItemLabel";
import PrintButton from "./PrintButton";

function NewBatch() {
  const location = useLocation();
  const queryParentSkuId = (parse(location.search).parent as string) || "";
  const { data, frontloadMeta, setData } = useFrontload(
    "new-batch-component",
    async ({ api }: FrontloadContext) => ({
      nextBatch: await api.getNextBatch(),
      parentSku: queryParentSkuId ? await api.getSku(queryParentSkuId) : null,
    })
  );
  const api = useContext(ApiContext);
  const { setAlertContent } = useContext(AlertContext);
  const history = useHistory();

  const [parentSkuId, setParentSkuId] = useState("");
  const [batchIdValue, setBatchIdValue] = useState("");
  const [nameValue, setNameValue] = useState("");
  const [codes, setCodes] = useState<Code[]>([]);
  const batchIdRef = useRef(null);

  useEffect(() => {
    if (parentSkuId) {
      api
        .getSku(parentSkuId)
        .then((sku) => setData((data) => ({ ...data, parentSku: sku })));
    } else {
      setData((data) => ({
        ...data,
        parentSku: null,
      }));
    }
  }, [parentSkuId]);

  useEffect(() => {
    setParentSkuId(queryParentSkuId);
  }, [queryParentSkuId]);

  function clearForm() {
    // setParentSkuId("");
    if (parentSkuId != queryParentSkuId) {
      history.push(
        stringifyUrl({ url: "/new/batch", query: { parent: parentSkuId } })
      );
    }
    setBatchIdValue("");
    setNameValue("");
    setCodes([]);
  }

  if (frontloadMeta.pending) return <div>Loading...</div>;
  if (frontloadMeta.error) throw Error("API Error");

  return (
    <form
      className="form"
      onSubmit={async (e) => {
        e.preventDefault();

        const ownedCodes = [];
        const associatedCodes = [];
        for (const code of codes) {
          if (code.value == "" || code.inherited) continue;
          switch (code.kind) {
          case "owned":
            ownedCodes.push(code.value);
            break;

          case "associated":
            associatedCodes.push(code.value);
            break;

          default:
            let _exhaustiveCheck: never; // eslint-disable-line
          }
        }
        const nextBatch =
          data.nextBatch.kind == "next-batch" ? data.nextBatch.state : "";
        const resp = await api.createBatch({
          id: batchIdValue || nextBatch,
          sku_id: parentSkuId,
          name: nameValue,
          owned_codes: ownedCodes,
          associated_codes: associatedCodes,
        });
        if (resp.kind == "status") {
          clearForm();
          setAlertContent({
            content: (
              <p>
                Success,{" "}
                <ItemLabel url={resp.Id} onClick={() => setAlertContent({})} />{" "}
                created.
              </p>
            ),
            mode: "success",
          });
          const nextBatch = await api.getNextBatch();
          setData((data) => ({ ...data, nextBatch }));
          batchIdRef.current.focus();
        } else {
          setAlertContent({
            content: <p>{resp.title}</p>,
            mode: "failure",
          });
        }
      }}
    >
      <h2 className="form-title">New Batch</h2>
      <label htmlFor="parent_sku_id" className="form-label">
        Parent Sku (optional)
      </label>
      <input
        type="text"
        id="parent_sku_id"
        name="parent_sku_id"
        className="form-single-code-input"
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
            data.nextBatch.state
          }
          value={batchIdValue}
          onChange={(e) => setBatchIdValue(e.target.value)}
        />
        <PrintButton
          value={
            batchIdValue ||
              data.nextBatch.state
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
        value={nameValue}
        onChange={(e) => setNameValue(e.target.value)}
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
