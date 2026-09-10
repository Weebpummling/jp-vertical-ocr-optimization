/**
 * Pane 1 - the zoomable page, auto-centred on the current cell.
 *
 * Cell rectangles arrive in the IIIF service's full-resolution pixel space, so
 * centring is a direct conversion into OpenSeadragon's viewport coordinates
 * (x / imageWidth) with no second lookup.
 */
/// <reference types="vite/client" />
import { useEffect, useRef, useState } from "react";
import OpenSeadragon from "openseadragon";
import type { Bbox } from "../api";

// The viewer's button sprites, resolved file by file at build time. Pointing
// OpenSeadragon at the node_modules directory worked under the dev server and
// nowhere else: the built workstation requested /node_modules/... and every
// zoom, home and full-page button rendered as a broken image.
const sprites = import.meta.glob<string>(
  "../../node_modules/openseadragon/build/openseadragon/images/*.png",
  { eager: true, query: "?url", import: "default" },
);
const sprite = (name: string) =>
  Object.entries(sprites).find(([file]) => file.endsWith(`/${name}.png`))?.[1] ?? "";
const button = (base: string) => ({
  REST: sprite(`${base}_rest`),
  GROUP: sprite(`${base}_grouphover`),
  HOVER: sprite(`${base}_hover`),
  DOWN: sprite(`${base}_pressed`),
});
const navImages = {
  zoomIn: button("zoomin"),
  zoomOut: button("zoomout"),
  home: button("home"),
  fullpage: button("fullpage"),
  rotateleft: button("rotateleft"),
  rotateright: button("rotateright"),
  flip: button("flip"),
  previous: button("previous"),
  next: button("next"),
};

interface Props {
  /** Local page image (see api.pageImageUrl) — not the institution's tiles. */
  imageUrl: string | null;
  focus: Bbox | null;
  /** Extra room around the focused cell, as a fraction of its size. */
  pad?: number;
}

export function Viewer({ imageUrl, focus, pad = 0.6 }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const osdRef = useRef<OpenSeadragon.Viewer | null>(null);
  const readyRef = useRef(false);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    if (!hostRef.current || !imageUrl) return;
    readyRef.current = false;
    setFailure(null);
    const viewer = OpenSeadragon({
      element: hostRef.current,
      // Each sprite is already a full URL; nothing to prefix.
      prefixUrl: "",
      navImages,
      // A single cached image rather than a tile pyramid: the page is already
      // on disk, and this keeps transcription working with no network at all.
      tileSources: { type: "image", url: imageUrl },
      showNavigator: true,
      navigatorPosition: "BOTTOM_RIGHT",
      gestureSettingsMouse: { clickToZoom: false },
      animationTime: 0.4,
      visibilityRatio: 1,
      minZoomLevel: 0.4,
    });
    viewer.addHandler("open", () => {
      readyRef.current = true;
    });
    viewer.addHandler("open-failed", (e: { message?: string }) => {
      setFailure(e?.message ?? "could not open the page image");
    });
    osdRef.current = viewer;
    return () => {
      viewer.destroy();
      osdRef.current = null;
    };
  }, [imageUrl]);

  useEffect(() => {
    const viewer = osdRef.current;
    if (!viewer || !focus) return;

    const panTo = () => {
      const item = viewer.world.getItemAt(0);
      if (!item) return;
      const imageWidth = item.getContentSize().x;
      const [x, y, w, h] = focus;
      const grow = Math.max(w, h) * pad;
      const rect = new OpenSeadragon.Rect(
        (x - grow) / imageWidth,
        (y - grow) / imageWidth,
        (w + grow * 2) / imageWidth,
        (h + grow * 2) / imageWidth,
      );
      viewer.viewport.fitBounds(rect, false);
    };

    if (readyRef.current) panTo();
    else viewer.addOnceHandler("open", panTo);
  }, [focus, pad]);

  if (!imageUrl) {
    return (
      <div className="viewer viewer--empty">
        <p>No page image.</p>
      </div>
    );
  }
  return (
    <>
      <div className="viewer" ref={hostRef} />
      {failure && <p className="viewer__error">Page image failed to load: {failure}</p>}
    </>
  );
}
