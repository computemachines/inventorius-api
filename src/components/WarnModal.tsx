import * as React from "react";
import { useContext, useEffect, useState } from "react";
import ReactModal from "react-modal";

import "../styles/WarnModal.css";

export default function WarnModal({
  onContinue,
  dangerousActionName,
  children,
}: {
  onContinue: () => void;
  dangerousActionName: string;
  children?: React.ReactNode;
}) {
  const [showModal, setShowModal] = useState(true);
  return (
    <ReactModal
      isOpen={showModal}
      onRequestClose={() => setShowModal(false)}
      className="warn-modal"
    >
      <button
        className="warn-modal__close-button"
        onClick={() => setShowModal(false)}
      >
        X
      </button>
      <h3>Are you sure?</h3>
      <button
        className="warn-modal__cancel-button"
        onClick={() => setShowModal(false)}
      >
        Cancel
      </button>
      <button className="warn-modal__dangerous-button" onClick={onContinue}>{dangerousActionName}</button>
    </ReactModal>
  );
}
