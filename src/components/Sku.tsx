import * as React from "react";
import { useFrontload } from "react-frontload";
import { generatePath, Prompt, useHistory, useParams } from "react-router-dom";
import { ApiContext, FrontloadContext } from "../api-client/inventory-api";
import ReactModal from "react-modal";
import { Link } from "react-router-dom";

import "../styles/Sku.css";
import "../styles/infoPanel.css";
import "../styles/warnModal.css";
import CodesInput from "./CodesInput";
import { FourOhFour } from "./FourOhFour";
import ItemLabel from "./ItemLabel";
import PrintButton from "./PrintButton";
import SkuItemLocations from "./SkuItemLocations";
import { useContext, useEffect, useState } from "react";
import { AlertContext } from "./Alert";

function Sku({ editable = false }: { editable?: boolean }) {
  const { id } = useParams<{ id: string }>();
  const { data, frontloadMeta, setData } = useFrontload(
    "sku-component",
    async ({ api }: FrontloadContext) => ({
      sku: await api.getSku(id),
    })
  );
  const { setAlertContent } = useContext(AlertContext);
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
    if (
      frontloadMeta.done &&
      data.sku.kind != "problem" &&
      saveState == "live"
    ) {
      setUnsavedName(data.sku.state.name);
      setUnsavedCodes([
        ...data.sku.state.owned_codes.map((code) => ({
          kind: "owned" as "owned",
          value: code,
        })),
        ...data.sku.state.associated_codes.map((code) => ({
          kind: "associated" as "associated",
          value: code,
        })),
      ]);
    }
  }, [frontloadMeta, saveState]);

  if (data?.sku.kind == "problem") {
    if (data.sku.type == "missing-resource") return <FourOhFour />;
    else return <h2>{data.sku.title}</h2>;
  } else {
    if (frontloadMeta.error) {
      return <div>Connection Error</div>;
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
              const resp = await data.sku.delete();
              if (resp.ok) {
                setAlertContent({ content: <p>Deleted</p>, mode: "success" });
                const updatedSku = await api.getSku(id);
                setData(() => ({ sku: updatedSku }));
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
          <div className="info-item-title">Sku Label</div>
          <div className="info-item-description">
            <ItemLabel link={false} label={id} />
            <PrintButton value={id} />
          </div>
        </div>
        {frontloadMeta.pending ? (
          "Loading..."
        ) : (
          <>
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
                <SkuItemLocations sku={data?.sku} />
              </div>
            </div>
            <div className="info-item">
              <div className="info-item-title">Codes</div>
              <div className="info-item-description">
                <CodesInput
                  codes={unsavedCodes}
                  setCodes={(codes) => {
                    setSaveState("unsaved");
                    setUnsavedCodes(codes);
                  }}
                  editable={editable}
                />
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
                    if (data.sku.kind == "problem") throw "impossible";
                    setSaveState("saving");
                    const resp = await data.sku.update({
                      name: unsavedName,
                      owned_codes: unsavedCodes
                        .filter(({ kind }) => kind == "owned")
                        .map(({ value }) => value),
                      associated_codes: unsavedCodes
                        .filter(({ kind }) => kind == "associated")
                        .map(({ value }) => value),
                    });
                    const json = await resp.json();

                    if (!resp.ok) {
                      setSaveState("unsaved");
                      setAlertContent({
                        content: <p>{json.title}</p>,
                        mode: "failure",
                      });
                    } else {
                      setSaveState("live");
                      setAlertContent({
                        content: <div>Saved!</div>,
                        mode: "success",
                      });
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
                <div
                  className="info-item-description"
                  style={{ display: "block" }}
                >
                  <Link
                    to={generatePath("/sku/:id/edit", { id })}
                    className="action-link"
                  >
                    Edit
                  </Link>
                  <Link to="#" className="action-link">
                    Receive
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
            )}{" "}
          </>
        )}
      </div>
    );
  }
}
export default Sku;
