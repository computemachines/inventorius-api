import * as React from "react";
import { useContext, useEffect, useState } from "react";
import { useFrontload } from "react-frontload";
import { ApiContext, FrontloadContext } from "../api-client/api-client";

import "../styles/form.css";

import { AlertContext } from "./Alert";
import ItemLabel from "./ItemLabel";
import PrintButton from "./PrintButton";

function NewBin() {
  const { setAlertContent } = useContext(AlertContext);
  const api = useContext(ApiContext);
  const [binIdValue, setBinIdValue] = useState("");
  let binIdPlaceholder = "Loading";

  const { data, setData, frontloadMeta } = useFrontload(
    "new-bin-component",
    async ({ api }: FrontloadContext) => ({
      nextBin: await api.getNextBin(),
    })
  );


  if (frontloadMeta.done)
    binIdPlaceholder = data.nextBin.state;

  return (
    <form
      className="form"
      onSubmit={async (e) => {
        e.preventDefault();

        const resp = await api.createBin({
          id: binIdValue || binIdPlaceholder,
          props: null,
        });
        if (resp.kind == "status") {
          setBinIdValue("");
          setAlertContent({
            content: (
              <p>
                Success,{" "}
                <ItemLabel url={resp.Id} onClick={(e) => setAlertContent({})} />{" "}
                created.
              </p>
            ),
            mode: "success",
          });
        } else {
          setAlertContent({
            content: <p>{resp.title}</p>,
            mode: "failure",
          });
        }
      }}
    >
      <h2 className="form-title">New Bin</h2>
      <label htmlFor="bin_id" className="form-label">
        Bin Label
      </label>
      <div className="flex-row">
        <input
          type="text"
          name="bin_id"
          id="bin_id"
          placeholder={binIdPlaceholder}
          className="form-single-code-input"
          value={binIdValue}
          onChange={(e) => setBinIdValue(e.target.value)}
        />
        <PrintButton value={binIdValue || binIdPlaceholder} />
      </div>
      <input type="submit" value="Submit" className="form-submit" />
    </form>
  );
}

export default NewBin;
