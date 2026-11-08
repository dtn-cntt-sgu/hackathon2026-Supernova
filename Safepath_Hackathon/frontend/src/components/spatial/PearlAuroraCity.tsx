"use client";

import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import type { CameraEvidence } from "../../types/contracts";

interface PearlAuroraCityProps {
  cameras: CameraEvidence[];
  camera: CameraEvidence | null;
  scene: number;
}

export function PearlAuroraCity({ cameras, camera, scene }: PearlAuroraCityProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);
  const sceneRef = useRef(scene);
  sceneRef.current = scene;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // Mobile check: bypass WebGL on screens < 768px to guarantee 60-120 FPS
    const isMobile = typeof window !== "undefined" && window.innerWidth < 768;
    if (isMobile) {
      setReady(true);
      return;
    }

    let isDisposed = false;
    let animId = 0;
    let isVisible = true;

    // 1. Scene setup: Transparent background for Pearl Aurora Gradient
    const threeScene = new THREE.Scene();

    // 2. Camera setup: Looking at the right-side hero quadrant
    const aspect = container.clientWidth / Math.max(container.clientHeight, 1);
    const threeCamera = new THREE.PerspectiveCamera(36, aspect, 1, 1000);
    threeCamera.position.set(0, 22, 70);

    // 3. WebGL Renderer with Alpha: true
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: true,
        powerPreference: "high-performance",
      });
      renderer.setSize(container.clientWidth, container.clientHeight);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.25));
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.05;
      renderer.shadowMap.enabled = false;
      container.appendChild(renderer.domElement);
    } catch {
      setReady(true);
      return;
    }

    // 4. Daylight Illumination
    const ambientLight = new THREE.AmbientLight("#FFFFFF", 0.95);
    threeScene.add(ambientLight);

    const sunLight = new THREE.DirectionalLight("#FFF8EE", 1.3);
    sunLight.position.set(50, 80, 40);
    threeScene.add(sunLight);

    const skyFill = new THREE.DirectionalLight("#C5E5FC", 0.6);
    skyFill.position.set(-40, 60, -30);
    threeScene.add(skyFill);

    // 5. Materials (Pearl White, Frosted Crystal Glass, Cyan Ribbons)
    const matPearl = new THREE.MeshLambertMaterial({
      color: "#FFFFFF",
    });

    const matCrystalGlass = new THREE.MeshStandardMaterial({
      color: "#D6EEFA",
      roughness: 0.08,
      metalness: 0.15,
      transparent: true,
      opacity: 0.6,
    });

    const matCyanAccent = new THREE.MeshStandardMaterial({
      color: "#168BD2",
      roughness: 0.15,
      metalness: 0.2,
      transparent: true,
      opacity: 0.85,
    });

    const matRiverWater = new THREE.MeshStandardMaterial({
      color: "#18B6AD",
      roughness: 0.1,
      metalness: 0.25,
      transparent: true,
      opacity: 0.55,
    });

    const matTransitThread = new THREE.MeshBasicMaterial({
      color: "#168BD2",
      transparent: true,
      opacity: 0.85,
    });

    // 6. Sculptural City Group (Firmly confined to right-hand background)
    const cityGroup = new THREE.Group();
    cityGroup.position.set(32, -3, -15);
    threeScene.add(cityGroup);

    // Saigon River Estuary Arc
    const riverCurve = new THREE.CatmullRomCurve3([
      new THREE.Vector3(-15, 0, -25),
      new THREE.Vector3(5, 0, -8),
      new THREE.Vector3(25, 0, 5),
      new THREE.Vector3(55, 0, -5),
    ]);
    const riverGeo = new THREE.TubeGeometry(riverCurve, 24, 7, 4, false);
    const riverMesh = new THREE.Mesh(riverGeo, matRiverWater);
    riverMesh.scale.set(1, 0.03, 1);
    riverMesh.position.y = 0.05;
    cityGroup.add(riverMesh);

    // Curving Cable-Stayed Bridge Arc
    const bridgeCurve = new THREE.CatmullRomCurve3([
      new THREE.Vector3(-2, 0.2, -18),
      new THREE.Vector3(10, 2.2, 0),
      new THREE.Vector3(22, 0.2, 18),
    ]);
    const bridgeGeo = new THREE.TubeGeometry(bridgeCurve, 20, 0.45, 6, false);
    const bridgeMesh = new THREE.Mesh(bridgeGeo, matPearl);
    cityGroup.add(bridgeMesh);

    // Sculptural Towers: ONLY Slender Tapered / Faceted Profiles (Zero Blocky Monoliths!)
    const towers = [
      // Landmark 81 Stepped Needle Spire
      { x: 14, z: -8, rTop: 0.6, rBot: 2.4, h: 25, type: "spire" },
      // Bitexco Lotus Fin Tower
      { x: 4, z: -16, rTop: 1.2, rBot: 2.2, h: 19, type: "taper" },
      // Waterfront Arc Spires
      { x: 24, z: 2, rTop: 0.8, rBot: 1.8, h: 15, type: "spire" },
      { x: 30, z: -14, rTop: 1.0, rBot: 2.0, h: 17, type: "taper" },
      // Distant Graceful Needles
      { x: 36, z: 6, rTop: 0.5, rBot: 1.5, h: 13, type: "needle" },
      { x: 20, z: -22, rTop: 0.6, rBot: 1.6, h: 14, type: "needle" },
    ];

    towers.forEach((t) => {
      const bGroup = new THREE.Group();
      bGroup.position.set(t.x, 0, t.z);

      if (t.type === "spire") {
        // Stepped faceted lower body
        const baseGeo = new THREE.CylinderGeometry(t.rBot * 0.7, t.rBot, t.h * 0.55, 8);
        const baseMesh = new THREE.Mesh(baseGeo, matPearl);
        baseMesh.position.y = (t.h * 0.55) / 2;
        bGroup.add(baseMesh);

        // Crystal needle spire
        const needleGeo = new THREE.ConeGeometry(t.rBot * 0.68, t.h * 0.45, 8);
        const needleMesh = new THREE.Mesh(needleGeo, matCrystalGlass);
        needleMesh.position.y = t.h * 0.55 + (t.h * 0.45) / 2;
        bGroup.add(needleMesh);

        // Luminous cyan tip beacon
        const tipGeo = new THREE.SphereGeometry(0.35, 6, 6);
        const tipMat = new THREE.MeshBasicMaterial({ color: "#168BD2" });
        const tip = new THREE.Mesh(tipGeo, tipMat);
        tip.position.y = t.h;
        bGroup.add(tip);
      } else if (t.type === "taper") {
        // Tapered crystal tower with cyan accent
        const geo = new THREE.CylinderGeometry(t.rTop, t.rBot, t.h, 7);
        const mesh = new THREE.Mesh(geo, matCrystalGlass);
        mesh.position.y = t.h / 2;
        bGroup.add(mesh);

        const finGeo = new THREE.ConeGeometry(t.rTop, 2.5, 7);
        const finMesh = new THREE.Mesh(finGeo, matCyanAccent);
        finMesh.position.y = t.h + 1.25;
        bGroup.add(finMesh);
      } else {
        // Slender needle
        const geo = new THREE.CylinderGeometry(t.rTop, t.rBot, t.h, 6);
        const mesh = new THREE.Mesh(geo, matPearl);
        mesh.position.y = t.h / 2;
        bGroup.add(mesh);
      }

      cityGroup.add(bGroup);
    });

    // Luminous Smart Transit Thread
    const transitCurve = new THREE.CatmullRomCurve3([
      new THREE.Vector3(-25, 0.8, -20),
      new THREE.Vector3(0, 1.2, -4),
      new THREE.Vector3(20, 1.3, 6),
      new THREE.Vector3(45, 0.8, 16),
    ]);
    const transitGeo = new THREE.TubeGeometry(transitCurve, 32, 0.28, 6, false);
    const transitMesh = new THREE.Mesh(transitGeo, matTransitThread);
    cityGroup.add(transitMesh);

    // 7. Render Loop with Scene Transition Modulation
    const currentPos = new THREE.Vector3(0, 22, 70);
    const currentTarget = new THREE.Vector3(26, 6, -10);

    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let clock = new THREE.Clock();

    const animate = () => {
      if (isDisposed) return;
      animId = requestAnimationFrame(animate);

      if (!isVisible) return;

      const delta = clock.getDelta();
      const time = clock.getElapsedTime();
      const activeScene = Math.max(0, Math.min(3, sceneRef.current));

      // In Act 0 (Hero): City group is visible in the right-hand hero background
      // In Acts 1, 2, 3: City group smoothly recedes down below the horizon so content is 100% clean!
      if (activeScene === 0) {
        cityGroup.visible = true;
        cityGroup.position.y = THREE.MathUtils.lerp(cityGroup.position.y, -3, 0.06);
        if (!prefersReducedMotion) {
          cityGroup.rotation.y = Math.sin(time * 0.12) * 0.02;
        }
      } else {
        cityGroup.position.y = THREE.MathUtils.lerp(cityGroup.position.y, -45, 0.06);
        if (cityGroup.position.y < -40) {
          cityGroup.visible = false;
        }
      }

      threeCamera.position.copy(currentPos);
      threeCamera.lookAt(currentTarget);

      renderer.render(threeScene, threeCamera);
    };

    animId = requestAnimationFrame(animate);
    setReady(true);

    const onVisibility = () => {
      isVisible = !document.hidden;
      if (isVisible) clock.start();
    };
    document.addEventListener("visibilitychange", onVisibility);

    const resizeObserver = new ResizeObserver(() => {
      if (!container || !renderer) return;
      const w = container.clientWidth;
      const h = Math.max(container.clientHeight, 1);
      threeCamera.aspect = w / h;
      threeCamera.updateProjectionMatrix();
      renderer.setSize(w, h);
    });
    resizeObserver.observe(container);

    return () => {
      isDisposed = true;
      cancelAnimationFrame(animId);
      document.removeEventListener("visibilitychange", onVisibility);
      resizeObserver.disconnect();

      threeScene.traverse((obj) => {
        if (obj instanceof THREE.Mesh) {
          obj.geometry?.dispose();
          if (Array.isArray(obj.material)) {
            obj.material.forEach((m) => m.dispose());
          } else {
            obj.material?.dispose();
          }
        }
      });
      renderer.dispose();
      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
    };
  }, []);

  return (
    <div
      ref={containerRef}
      className="observatory-map-canvas absolute inset-0 w-full h-full pointer-events-none"
      aria-hidden="true"
    >
      {/* Mobile-only crisp vector pearl architectural skyline */}
      <div className="md:hidden absolute inset-0 flex items-end justify-center pointer-events-none opacity-30 pb-16">
        <svg
          viewBox="0 0 400 160"
          className="w-full max-h-[140px] text-sky-400"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <path
            d="M50 160 V110 H75 V160 M85 160 V80 H115 V160 M125 160 V50 H155 V160 M165 160 V30 L180 15 L195 30 V160 M205 160 V65 H235 V160 M245 160 V95 H275 V160 M285 160 V75 H315 V160 M325 160 V120 H355 V160"
            stroke="currentColor"
            strokeWidth="1.2"
            strokeOpacity="0.4"
          />
          <path
            d="M0 145 Q100 135 200 142 T400 138"
            stroke="#18B6AD"
            strokeWidth="2"
            strokeOpacity="0.5"
          />
        </svg>
      </div>
    </div>
  );
}
