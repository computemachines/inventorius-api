import * as React from "react";
import { useFrontload } from "react-frontload";
import { ApiContext, FrontloadContext } from "../api-client/api-client";
import { ToastContext } from "./Toast";

function Audit() {
  const { setToastContent } = React.useContext(ToastContext);
  const api = React.useContext(ApiContext);
  const [binIdValue, setBinIdValue] = React.useState("");
  const { data, setData, frontloadMeta } = useFrontload(
    "audit-component",
    async ({ api }: FrontloadContext) => ({})
  );

  return (
    <form>
      <h2 className="form-title">Audit</h2>
      <label htmlFor="bin_id" className="form-label">
        Bin Label
      </label>
      <div className="flex-row">
        <input
          type="text"
          name="bin_id"
          id="bin_id"
          className="form-single-code-input"
          value={binIdValue}
          onChange={(e) => setBinIdValue(e.target.value)}
        />
      </div>
    </form>
  );
}

export default Audit;
