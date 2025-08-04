import * as React from "react";
import { useFrontload } from "react-frontload";
import { generatePath, Prompt, useHistory, useParams } from "react-router-dom";
import { ApiContext, FrontloadContext } from "../api-client/api-client";
import { Sku as ApiSku } from "../api-client/data-models";
import ReactModal from "react-modal";
import { Link } from "react-router-dom";

import "../styles/infoPanel.css";
import CodesInput, { Code } from "./CodesInput";
import { FourOhFour } from "./FourOhFour";
import ItemLabel from "./ItemLabel";
import PrintButton from "./PrintButton";
import ItemLocations from "./ItemLocations";
import { useContext, useEffect, useState } from "react";
import { ToastContext } from "./Toast";
import { stringifyUrl } from "query-string";

function Sku({ editable = false }: { editable?: boolean }) {
  const { id } = useParams<{ id: string }>();
  const { data, frontloadMeta, setData } = useFrontload(
    "sku-component",
    async ({ api }: FrontloadContext) => {
      const sku = await api.getSku(id);
      const skuBins = sku.kind == "sku" ? await sku.bins() : sku;
      return {
        sku,
        skuBins,
      };
    }
  );
  const { setToastContent: setAlertContent } = useContext(ToastContext);
  const [showModal, setShowModal] = useState(false);
  const [saveState, setSaveState] = useState<"live" | "unsaved" | "saving">(
    "live"
  );
  const history = useHistory();
  const [unsavedName, setUnsavedName] = useState("");
  const [unsavedCodes, setUnsavedCodes] = useState([]);
  const api = useContext(ApiContext);

  useEffect(() => {
    if (!editable) setSaveState("live");
  }, [editable]);

  useEffect(() => {
    // if data loads and not editing
    if (
      frontloadMeta.done &&
      !frontloadMeta.error &&
      data.sku.kind != "problem" &&
      saveState == "live"
    ) {
      setUnsavedName(data.sku.state.name);
      const newUnsavedCodes = [
        ...data.sku.state.owned_codes.map((code) => ({
          kind: "owned" as const,
          value: code,
        })),
        ...data.sku.state.associated_codes.map((code) => ({
          kind: "associated" as const,
          value: code,
        })),
      ];
      setUnsavedCodes(newUnsavedCodes);
    }
  }, [frontloadMeta, saveState, data]);

  if (frontloadMeta.pending) {
    return <div>Loading...</div>;
  }
  if (frontloadMeta.error) {
    return <div>Connection Error</div>;
  }
  if (data.sku.kind == "problem") {
    if (data.sku.type == "missing-resource") return <FourOhFour />;
    else return <h2>{data.sku.title}</h2>;
  }

  function isCodesEmpty(codes: Code[]): boolean {
    return codes.length == 0 || codes.every(({ value }) => value == "");
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
            if (data.sku.kind == "problem") throw "impossible";
            const resp = await api.hydrate(data.sku).delete();
            // setShowModal(false); // this doesn't seem to be necessary?
            if (resp.kind == "status") {
              setAlertContent({ content: <p>Deleted</p>, mode: "success" });
              const updatedSku = await api.getSku(id);
              const updatedSkuBins =
                updatedSku.kind == "sku" ? await updatedSku.bins() : updatedSku;
              setData(() => ({ sku: updatedSku, skuBins: updatedSkuBins }));
            } else {
              setAlertContent({
                content: <p>{resp.title}</p>,
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
        <div className="info-item-title">Sku Label</div>
        <div className="info-item-description">
          <ItemLabel link={false} label={id} />
          <PrintButton value={id} />
        </div>
      </div>

      <div className="info-item">
        <div className="info-item-title">Name</div>
        <div className="info-item-description">
          {editable ? (
            <input
              className="item-description-oneline"
              value={unsavedName}
              onChange={(e) => {
                setSaveState("unsaved");
                setUnsavedName(e.target.value);
              }}
            />
          ) : (
            <div className="item-description-oneline">{unsavedName}</div>
          )}
        </div>
      </div>
      <div className="info-item">
        <div className="info-item-title">Derived Batches</div>
        <div className="info-item-description">TODO</div>
      </div>
      <div className="info-item">
        <div className="info-item-title">Locations</div>
        <div className="info-item-description">
          {data.skuBins.kind == "sku-locations" ? (
            <ItemLocations itemLocations={data.skuBins} />
          ) : (
            "Problem loading locations."
          )}
        </div>
      </div>
      <div className="info-item">
        <div className="info-item-title">Codes</div>
        <div className="info-item-description">
          {isCodesEmpty(unsavedCodes) && !editable ? (
            "None"
          ) : (
            <CodesInput
              codes={unsavedCodes}
              setCodes={(codes) => {
                setSaveState("unsaved");
                setUnsavedCodes(codes);
              }}
              editable={editable}
            />
          )}
        </div>
      </div>
      {editable ? (
        <div className="edit-controls">
          <button
            className="edit-controls-cancel-button"
            onClick={(e) => {
              history.push(generatePath("/sku/:id", { id }));
            }}
          >
            Cancel
          </button>
          <button
            className="edit-controls-save-button"
            onClick={async () => {
              if (data.sku.kind == "problem") throw Error("impossible");
              setSaveState("saving");
              const resp = await api.hydrate(data.sku).update({
                name: unsavedName,
                owned_codes: unsavedCodes
                  .filter(({ kind, value }) => kind == "owned" && value)
                  .map(({ value }) => value),
                associated_codes: unsavedCodes
                  .filter(({ kind, value }) => kind == "associated" && value)
                  .map(({ value }) => value),
              });

              if (resp.kind == "problem") {
                setSaveState("unsaved");
                setAlertContent({
                  content: <p>{resp.title}</p>,
                  mode: "failure",
                });
              } else {
                setSaveState("live");
                setAlertContent({
                  content: <div>{resp.status}</div>,
                  mode: "success",
                });

                const updatedSku = await api.getSku(id);

                setData(({ skuBins }) => ({
                  sku: updatedSku,
                  skuBins,
                }));

                history.push(generatePath("/sku/:id", { id }));
              }
            }}
            disabled={saveState == "saving"}
          >
            {saveState == "saving" ? "Saving..." : "Save"}
          </button>
        </div>
      ) : (
        <div className="info-item">
          <div className="info-item-title">Actions</div>
          <div className="info-item-description" style={{ display: "block" }}>
            <Link
              to={generatePath("/sku/:id/edit", { id })}
              className="action-link"
            >
              Edit
            </Link>
            <Link
              to={stringifyUrl({ url: "/receive", query: { item: id } })}
              className="action-link"
            >
              Receive
            </Link>
            <Link
              to={stringifyUrl({
                url: "/release",
                query: { item: id },
              })}
              className="action-link"
            >
              Release
            </Link>
            <Link
              to="#"
              className="action-link"
              onClick={() => setShowModal(true)}
            >
              Delete?
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}

export default Sku;
