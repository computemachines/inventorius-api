import * as React from "react";
import { useContext, useEffect, useState } from "react";
import { useFrontload } from "react-frontload";
import { Prompt, useHistory, useParams } from "react-router-dom";
import { ApiContext, FrontloadContext } from "../api-client/inventory-api";
// import { Problem, Sku as ApiSku } from "../api-client/data-models";
import ReactModal from "react-modal";

import "../styles/infoPanel.css";
import "../styles/warnModal.css";
import { AlertContext } from "./Alert";
import { Code } from "./CodesInput";
import { FourOhFour } from "./FourOhFour";

function Batch({ editable = false }: { editable?: boolean }) {
  const { id } = useParams<{ id: string }>();
  const { data, frontloadMeta, setData } = useFrontload(
    "batch-component",
    async ({ api }: FrontloadContext) => {
      const batch = await api.getBatch(id);
      const parentSku =
        batch.kind == "batch" && batch.state.sku_id
          ? await api.getSku(batch.state.sku_id)
          : null;
      const batchBins = batch.kind == "batch" ? await batch.bins() : null;
      return { batch, parentSku, batchBins };
    }
  );
  const { setAlertContent } = useContext(AlertContext);
  const [showModal, setShowModal] = useState(false);
  const [saveState, setSaveState] = useState<"live" | "unsaved" | "saving">(
    "live"
  );
  const history = useHistory();
  const [usavedParentSkuId, setUsavedParentSkuId] = useState("");
  const [unsavedName, setUnsavedName] = useState("");
  const [unsavedCodes, setUnsavedCodes] = useState<Code[]>([]);
  const api = useContext(ApiContext);

  useEffect(() => {
    if (!editable) setSaveState("live");
  }, [editable]);

  useEffect(() => {
    if (
      frontloadMeta.done &&
      data.batch.kind != "problem" &&
      saveState == "live"
    ) {
      setUnsavedName(data.batch.state.name);
      setUnsavedCodes([
        ...data.batch.state.owned_codes.map((value) => ({
          value,
          kind: "owned" as "owned",
        })),
        ...data.batch.state.associated_codes.map((value) => ({
          value,
          kind: "associated" as "associated",
        })),
      ]);
    }
  }, [frontloadMeta, data, saveState]);

  if (frontloadMeta.pending) return <div>Loading...</div>;
  if (frontloadMeta.error) return <div>Connection Error</div>;
  if (data.batch.kind == "problem") {
    if (data.batch.type == "missing-resource") return <FourOhFour />;
    else return <div>{data.batch.title}</div>;
  }

  return (
    <div className="info-panel">
      <Prompt
        message="Leave without saving changes?"
        when={saveState != "live"}
      />
      <ReactModal
        isOpen={showModal}
        onRequestClose={() => setShowModal(false)}
        className="warn-modal"
      >
        <button className="modal-close" onClick={() => setShowModal(false)}>
          X
        </button>
        <h3>Are you sure?</h3>
        <button onClick={() => setShowModal(false)}>Cancel</button>
        <button
          onClick={async () => {
            if (data.batch.kind == "problem") throw "impossible";
            const resp = await api.hydrate(data.batch).delete();
            // setShowModal(false); // this doesn't seem to be necessary?
            if (resp.ok) {
              setAlertContent({ content: <p>Deleted</p>, mode: "success" });
              const updatedBatch = await api.getBatch(id);
              const updatedParentSku =
                updatedBatch.kind == "batch"
                  ? await api.getSku(updatedBatch.state.sku_id)
                  : null;
              const updatedBatchBins =
                updatedBatch.kind == "batch" ? await updatedBatch.bins() : null;
              setData(() => ({
                batch: updatedBatch,
                parentSku: updatedParentSku,
                batchBins: updatedBatchBins,
              }));
            } else {
              const json = await resp.json();
              setAlertContent({
                content: <p>{json.title}</p>,
                mode: "failure",
              });
            }
          }}
          className="button-danger"
        >
          Delete
        </button>
      </ReactModal>
      <div className="info-item">
        <div className="info-item-title">Parent Sku</div>
        <div className="info-item-description"></div>
      </div>
      <div className="info-item">
        <div className="info-item-title">Batch Label</div>
        <div className="info-item-description"></div>
      </div>
      <div className="info-item">
        <div className="info-item-title">Name</div>
        <div className="info-item-description"></div>
      </div>
      <div className="info-item">
        <div className="info-item-title">Codes</div>
        <div className="info-item-description"></div>
      </div>
      <div className="info-item">
        <div className="info-item-title">Actions</div>
        <div className="info-item-description"></div>
      </div>
    </div>
  );
}
export default Batch;
