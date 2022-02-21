import * as React from 'react';
import { useEffect, useRef, useState } from 'react';
import fetch from "cross-fetch";


function FileUpload() {
  const [memo, setMemo] = useState("");
  const [storedMemo, setStoredMemo] = useState("");


  return <div><form onSubmit={async (e) => {
    e.preventDefault();

    const data = new FormData();
    data.set('memo', memo);
    fetch("/api/memo", {method:"POST", body: data});

  }}>
    <input type="text" name="memo" value={memo} onChange={(e)=>setMemo(e.target.value)}/>
    <input type="submit" />
  </form>
  
  <h1>{storedMemo}</h1>
  <button onClick={async (e) => {
    const resp = await fetch("/api/memo");
    const text = await resp.text();
    setStoredMemo(text);
  }} >Get Memo</button>;
  </div>;
}

export default FileUpload;