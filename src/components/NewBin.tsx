import * as React from "react";
import { useContext, useEffect, useState } from "react";
import { useFrontload } from "react-frontload";
import { FrontloadContext } from "../api-client/inventory-api";

import "../styles/form.css";

import AlertContext from "./AlertContext";

function NewBin() {
  const { setAlertContent } = useContext(AlertContext);
  const [binId, setBinId] = useState("Loading");

  const { data, frontloadMeta } = useFrontload(
    "new-bin-component",
    async ({ api }: FrontloadContext) => ({
      nextBinId: await api.getNextBinId(),
    })
  );

  useEffect(() => {
    if (frontloadMeta.error) setBinId("API Error");
    if (frontloadMeta.done) setBinId(data.nextBinId.state);
  }, [frontloadMeta]);

  return (
    <form
      className="form"
      onSubmit={(e) => {
        setAlertContent(<h1>Submitted form!!</h1>);
        e.preventDefault();
      }}
    >
      <h2 className="form-title">New Bin</h2>
      <label htmlFor="bin_id" className="form-label">
        Bin Label
      </label>
      <input
        type="text"
        name="bin_id"
        id="bin_id"
        placeholder={binId}
        className="form-single-code-input"
      />
      <button className="form-print-button">Print</button>
      <input type="submit" value="Submit" className="form-submit" />
    </form>
  );
}

export default NewBin;
