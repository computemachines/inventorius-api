import * as React from "react";
import { useContext, useEffect, useState } from "react";
import { useFrontload } from "react-frontload";
import { FrontloadContext } from "../api-client/inventory-api";

import "../styles/form.css";

import AlertContext from "./AlertContext";
import ItemLabel from "./ItemLabel";

function NewBin() {
  const { setAlertContent } = useContext(AlertContext);
  const [binIdValue, setBinIdValue] = useState("");
  let binIdPlaceholder = "Loading";

  const { data, setData, frontloadMeta } = useFrontload(
    "new-bin-component",
    async ({ api }: FrontloadContext) => ({
      api,
      nextBin: await api.getNextBin(),
    })
  );

  if (frontloadMeta.error) binIdPlaceholder = "API Error";
  if (frontloadMeta.done) binIdPlaceholder = data.nextBin.state;

  return (
    <form
      className="form"
      onSubmit={(e) => {
        let binId;
        if (frontloadMeta.done) {
          binId = data.nextBin.state;
        }
        if (binIdValue) binId = binIdValue;

        data.nextBin.create().then((resp) => {
          if (resp.ok) setAlertContent("Success");
          else setAlertContent("Failure");

          data.api
            .getNextBin()
            .then((nextBin) => setData((data) => ({ ...data, nextBin })));
        });

        e.preventDefault();
      }}
    >
      {frontloadMeta.done ? <ItemLabel label={data.nextBin.state} /> : null}
      <h2 className="form-title">New Bin</h2>
      <label htmlFor="bin_id" className="form-label">
        Bin Label
      </label>
      <input
        type="text"
        name="bin_id"
        id="bin_id"
        placeholder={binIdPlaceholder}
        className="form-single-code-input"
      />
      <button className="form-print-button">Print</button>
      <input type="submit" value="Submit" className="form-submit" />
    </form>
  );
}

export default NewBin;
