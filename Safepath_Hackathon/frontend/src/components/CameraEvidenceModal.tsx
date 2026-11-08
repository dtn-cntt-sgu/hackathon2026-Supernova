"use client";

import { CameraProxyModal } from "./CameraProxyModal";
import type { CameraEvidence } from "../types/contracts";

/** Shared source/overlay viewer; inference starts only when the user selects Overlay. */
export function CameraEvidenceModal({ camera, onClose }: {
  camera: CameraEvidence | null; onClose: () => void; inspector?: boolean;
}) {
  return <CameraProxyModal camera={camera} onClose={onClose} />;
}
