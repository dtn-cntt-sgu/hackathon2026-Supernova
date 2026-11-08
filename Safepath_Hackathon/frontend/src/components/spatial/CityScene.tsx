"use client";

import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import type { CameraEvidence } from "../../types/contracts";

interface CitySceneProps {
  cameras: CameraEvidence[];
  camera: CameraEvidence | null;
  scene: number;
}

interface ActCameraTarget {
  pos: THREE.Vector3;
  target: THREE.Vector3;
  fov: number;
}

export function CityScene({ cameras, camera, scene }: CitySceneProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const sceneRef = useRef(scene);
  sceneRef.current = scene;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // Check mobile or touch - on mobile screens (< 768px), bypass heavy Three.js canvas to guarantee 60-120 FPS
    const isMobileScreen = typeof window !== "undefined" && window.innerWidth < 768;
    if (isMobileScreen) {
      setReady(true);
      return;
    }

    // Check WebGL support
    try {
      const testCanvas = document.createElement("canvas");
      const gl = testCanvas.getContext("webgl2") || testCanvas.getContext("webgl");
      if (!gl) {
        setFailed(true);
        return;
      }
    } catch {
      setFailed(true);
      return;
    }

    let isDisposed = false;
    let animId = 0;

    // 1. Scene & Daylight Atmosphere
    const threeScene = new THREE.Scene();
    threeScene.background = new THREE.Color("#EAF3FB");
    threeScene.fog = new THREE.Fog("#DDEAF6", 160, 560);

    // 2. Camera setup
    const aspect = container.clientWidth / Math.max(container.clientHeight, 1);
    const threeCamera = new THREE.PerspectiveCamera(45, aspect, 1, 1200);
    threeCamera.position.set(0, 180, 260);

    // 3. WebGL Renderer (Optimized: No heavy shadow maps to ensure ultra-smooth 60fps)
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        antialias: true,
        powerPreference: "high-performance",
        alpha: false,
      });
      renderer.setSize(container.clientWidth, container.clientHeight);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.25));
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.0;
      renderer.shadowMap.enabled = false;
      container.appendChild(renderer.domElement);
    } catch {
      setFailed(true);
      return;
    }

    // 4. Daylight Lighting Architecture (Clean & performant)
    const sunLight = new THREE.DirectionalLight("#FFF6E5", 1.35);
    sunLight.position.set(130, 220, 110);
    threeScene.add(sunLight);

    // Clear ambient sky & ground illumination
    const hemiLight = new THREE.HemisphereLight("#C8E2F8", "#9AB8D2", 0.52);
    threeScene.add(hemiLight);

    // Soft cool fill light
    const fillLight = new THREE.DirectionalLight("#90C2EB", 0.35);
    fillLight.position.set(-100, 110, -80);
    threeScene.add(fillLight);

    // 5. Urban Ground & River Architecture
    const groundGroup = new THREE.Group();
    threeScene.add(groundGroup);

    // Base daylight terrain (soft slate mist)
    const groundGeo = new THREE.PlaneGeometry(600, 600, 1, 1);
    const groundMat = new THREE.MeshStandardMaterial({
      color: "#D1E1EF",
      roughness: 0.78,
      metalness: 0.05,
    });
    const groundMesh = new THREE.Mesh(groundGeo, groundMat);
    groundMesh.rotation.x = -Math.PI / 2;
    groundMesh.position.y = -0.1;
    groundMesh.receiveShadow = true;
    groundGroup.add(groundMesh);

    // Saigon River waterway curve (vibrant cyan-blue water)
    const riverGeo = new THREE.PlaneGeometry(600, 52, 32, 1);
    const riverMat = new THREE.MeshStandardMaterial({
      color: "#2097DB",
      roughness: 0.16,
      metalness: 0.32,
      transparent: true,
      opacity: 0.9,
    });
    const riverMesh = new THREE.Mesh(riverGeo, riverMat);
    riverMesh.rotation.x = -Math.PI / 2;
    riverMesh.rotation.z = Math.PI / 6;
    riverMesh.position.set(-30, 0.05, -20);
    riverMesh.receiveShadow = true;
    groundGroup.add(riverMesh);

    // 6. Instanced City Buildings (Pearl White, Architectural Blue, Frosted Glass)
    const buildingCount = 140;
    const boxGeo = new THREE.BoxGeometry(1, 1, 1);

    // Three architectural styles with distinct shading & massing
    const matConcrete = new THREE.MeshStandardMaterial({
      color: "#E8F0F7",
      roughness: 0.42,
      metalness: 0.08,
    });
    const matPearl = new THREE.MeshStandardMaterial({
      color: "#A2C7E5",
      roughness: 0.32,
      metalness: 0.18,
    });
    const matGlass = new THREE.MeshPhysicalMaterial({
      color: "#54B2E8",
      roughness: 0.1,
      metalness: 0.12,
      transmission: 0.42,
      transparent: true,
      opacity: 0.9,
    });

    const instConcrete = new THREE.InstancedMesh(boxGeo, matConcrete, Math.floor(buildingCount * 0.45));
    instConcrete.castShadow = true;
    instConcrete.receiveShadow = true;

    const instPearl = new THREE.InstancedMesh(boxGeo, matPearl, Math.floor(buildingCount * 0.35));
    instPearl.castShadow = true;
    instPearl.receiveShadow = true;

    const instGlass = new THREE.InstancedMesh(boxGeo, matGlass, Math.floor(buildingCount * 0.2));
    instGlass.castShadow = true;
    instGlass.receiveShadow = true;

    const dummy = new THREE.Object3D();
    const cityExtent = 280;
    const gridCols = 12;
    const gridRows = 12;
    const colSpacing = cityExtent / gridCols;
    const rowSpacing = cityExtent / gridRows;

    let idxC = 0, idxP = 0, idxG = 0;

    for (let c = 0; c < gridCols; c++) {
      for (let r = 0; r < gridRows; r++) {
        // Skip some slots for road boulevards and river
        const x = (c - gridCols / 2) * colSpacing + (Math.random() - 0.5) * 4;
        const z = (r - gridRows / 2) * rowSpacing + (Math.random() - 0.5) * 4;

        // Skip river corridor
        const distToRiver = Math.abs(x * Math.sin(Math.PI / 6) - z * Math.cos(Math.PI / 6));
        if (distToRiver < 28) continue;
        // Skip central junction plaza
        if (Math.hypot(x, z) < 18) continue;

        const w = 8 + Math.random() * 8;
        const d = 8 + Math.random() * 8;
        // Taller in center, lower at outskirts
        const centerDist = Math.hypot(x, z);
        const h = Math.max(12, 100 - centerDist * 0.42 + Math.random() * 30);

        dummy.position.set(x, h / 2, z);
        dummy.scale.set(w, h, d);
        dummy.updateMatrix();

        const rand = Math.random();
        if (rand < 0.45 && idxC < instConcrete.count) {
          instConcrete.setMatrixAt(idxC++, dummy.matrix);
        } else if (rand < 0.8 && idxP < instPearl.count) {
          instPearl.setMatrixAt(idxP++, dummy.matrix);
        } else if (idxG < instGlass.count) {
          instGlass.setMatrixAt(idxG++, dummy.matrix);
        }
      }
    }

    instConcrete.instanceMatrix.needsUpdate = true;
    instPearl.instanceMatrix.needsUpdate = true;
    instGlass.instanceMatrix.needsUpdate = true;

    threeScene.add(instConcrete);
    threeScene.add(instPearl);
    threeScene.add(instGlass);

    // 7. Glowing Transit Network Corridors
    const roadGroup = new THREE.Group();
    threeScene.add(roadGroup);

    // Primary safe corridor: Vibrant Blue (#168BD2) with Teal Halo (#18B6AD)
    const primaryRouteCurve = new THREE.CatmullRomCurve3([
      new THREE.Vector3(-140, 0.4, -120),
      new THREE.Vector3(-60, 0.4, -60),
      new THREE.Vector3(0, 0.4, 0),
      new THREE.Vector3(70, 0.4, 50),
      new THREE.Vector3(130, 0.4, 110),
    ]);
    const primaryTubeGeo = new THREE.TubeGeometry(primaryRouteCurve, 64, 1.8, 8, false);
    const primaryTubeMat = new THREE.MeshBasicMaterial({
      color: "#18B6AD",
      transparent: true,
      opacity: 0.95,
    });
    const primaryRouteMesh = new THREE.Mesh(primaryTubeGeo, primaryTubeMat);
    roadGroup.add(primaryRouteMesh);

    // Secondary corridor (turns Amber in Act 2)
    const warningRouteCurve = new THREE.CatmullRomCurve3([
      new THREE.Vector3(-120, 0.35, 80),
      new THREE.Vector3(-40, 0.35, 30),
      new THREE.Vector3(0, 0.35, 0),
      new THREE.Vector3(60, 0.35, -40),
      new THREE.Vector3(110, 0.35, -90),
    ]);
    const warningTubeGeo = new THREE.TubeGeometry(warningRouteCurve, 64, 1.4, 8, false);
    const warningTubeMat = new THREE.MeshBasicMaterial({
      color: "#168BD2",
      transparent: true,
      opacity: 0.85,
    });
    const warningRouteMesh = new THREE.Mesh(warningTubeGeo, warningTubeMat);
    roadGroup.add(warningRouteMesh);

    // Cross city secondary road lines (distinct urban slate with markings)
    const crossRoadGeo = new THREE.PlaneGeometry(360, 7);
    const crossRoadMat = new THREE.MeshStandardMaterial({
      color: "#6C8CA5",
      roughness: 0.65,
      metalness: 0.05,
    });
    const roadX = new THREE.Mesh(crossRoadGeo, crossRoadMat);
    roadX.rotation.x = -Math.PI / 2;
    roadX.position.y = 0.08;
    roadX.receiveShadow = true;
    roadGroup.add(roadX);

    const roadZ = new THREE.Mesh(crossRoadGeo, crossRoadMat);
    roadZ.rotation.x = -Math.PI / 2;
    roadZ.rotation.z = Math.PI / 2;
    roadZ.position.y = 0.08;
    roadZ.receiveShadow = true;
    roadGroup.add(roadZ);

    // Road dashed white centerlines for realism
    const dashLineGeo = new THREE.PlaneGeometry(360, 0.4);
    const dashLineMat = new THREE.MeshBasicMaterial({ color: "#FFFFFF", opacity: 0.85, transparent: true });
    const dashLineX = new THREE.Mesh(dashLineGeo, dashLineMat);
    dashLineX.rotation.x = -Math.PI / 2;
    dashLineX.position.y = 0.09;
    roadGroup.add(dashLineX);

    const dashLineZ = new THREE.Mesh(dashLineGeo, dashLineMat);
    dashLineZ.rotation.x = -Math.PI / 2;
    dashLineZ.rotation.z = Math.PI / 2;
    dashLineZ.position.y = 0.09;
    roadGroup.add(dashLineZ);

    // 8. Dynamic Traffic Particle Pulses (Moving vehicles along roads)
    const vehicleCount = 36;
    const vehiclePoints = new Float32Array(vehicleCount * 3);
    const vehicleSpeeds: number[] = [];
    const vehicleCurves: boolean[] = [];

    for (let i = 0; i < vehicleCount; i++) {
      vehicleSpeeds.push(0.0015 + Math.random() * 0.002);
      vehicleCurves.push(Math.random() > 0.5);
    }

    const vehicleGeo = new THREE.BufferGeometry();
    vehicleGeo.setAttribute("position", new THREE.BufferAttribute(vehiclePoints, 3));
    const vehicleMat = new THREE.PointsMaterial({
      color: "#168BD2",
      size: 4.5,
      transparent: true,
      opacity: 0.95,
      blending: THREE.NormalBlending,
    });
    const vehicleSystem = new THREE.Points(vehicleGeo, vehicleMat);
    threeScene.add(vehicleSystem);

    // 9. Act 2: GPU Daylight Rain Particles System
    const rainCount = 1200;
    const rainPositions = new Float32Array(rainCount * 3);
    for (let i = 0; i < rainCount; i++) {
      rainPositions[i * 3] = (Math.random() - 0.5) * 320;
      rainPositions[i * 3 + 1] = Math.random() * 140;
      rainPositions[i * 3 + 2] = (Math.random() - 0.5) * 320;
    }
    const rainGeo = new THREE.BufferGeometry();
    rainGeo.setAttribute("position", new THREE.BufferAttribute(rainPositions, 3));
    const rainMat = new THREE.PointsMaterial({
      color: "#B2D3EE",
      size: 1.8,
      transparent: true,
      opacity: 0, // Starts at 0 in Act 1, fades up in Act 2
    });
    const rainSystem = new THREE.Points(rainGeo, rainMat);
    threeScene.add(rainSystem);

    // 10. Act 3: Computer Vision Visual Effects at Main Junction
    const cvGroup = new THREE.Group();
    threeScene.add(cvGroup);

    // 3D Bounding Boxes around simulated vehicles at junction (center [0,0,0])
    const bboxGroup = new THREE.Group();
    const bboxMatCar = new THREE.LineBasicMaterial({ color: "#18B6AD", linewidth: 2 });
    const bboxMatBike = new THREE.LineBasicMaterial({ color: "#168BD2", linewidth: 2 });

    const createBBox = (w: number, h: number, d: number, mat: THREE.LineBasicMaterial) => {
      const geo = new THREE.BoxGeometry(w, h, d);
      const edges = new THREE.EdgesGeometry(geo);
      return new THREE.LineSegments(edges, mat);
    };

    const bbox1 = createBBox(4, 3, 7, bboxMatCar);
    bbox1.position.set(-6, 1.6, 4);
    bboxGroup.add(bbox1);

    const bbox2 = createBBox(2, 2.5, 3.5, bboxMatBike);
    bbox2.position.set(5, 1.3, -5);
    bboxGroup.add(bbox2);

    const bbox3 = createBBox(4.2, 3, 7.5, bboxMatCar);
    bbox3.position.set(7, 1.6, 9);
    bboxGroup.add(bbox3);

    cvGroup.add(bboxGroup);

    // Holographic Water Segmentation Ripple Mesh
    const waterSegGeo = new THREE.PlaneGeometry(36, 36, 16, 16);
    const waterSegMat = new THREE.MeshBasicMaterial({
      color: "#38BDF8",
      wireframe: true,
      transparent: true,
      opacity: 0, // Activated in Act 3
    });
    const waterSegMesh = new THREE.Mesh(waterSegGeo, waterSegMat);
    waterSegMesh.rotation.x = -Math.PI / 2;
    waterSegMesh.position.set(-14, 0.45, -8);
    cvGroup.add(waterSegMesh);

    // Holographic Camera Beacon Tower
    const beaconGeo = new THREE.CylinderGeometry(0.5, 0.5, 18, 8);
    const beaconMat = new THREE.MeshBasicMaterial({ color: "#168BD2", transparent: true, opacity: 0.85 });
    const beaconMesh = new THREE.Mesh(beaconGeo, beaconMat);
    beaconMesh.position.set(0, 9, 0);
    cvGroup.add(beaconMesh);

    // Radiating radar scan rings
    const ringGeo = new THREE.RingGeometry(2, 2.6, 32);
    const ringMat = new THREE.MeshBasicMaterial({
      color: "#18B6AD",
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0,
    });
    const ringMesh = new THREE.Mesh(ringGeo, ringMat);
    ringMesh.rotation.x = -Math.PI / 2;
    ringMesh.position.set(0, 0.6, 0);
    cvGroup.add(ringMesh);

    // 11. Camera Positions per Act
    const actTargets: ActCameraTarget[] = [
      // Act 1 (Scene 0): Wide Aerial Living City
      {
        pos: new THREE.Vector3(0, 155, 230),
        target: new THREE.Vector3(0, 12, 0),
        fov: 44,
      },
      // Act 2 (Scene 1): Street-level Hazard Corridor (Rain & amber warnings)
      {
        pos: new THREE.Vector3(-45, 38, 70),
        target: new THREE.Vector3(10, 8, -20),
        fov: 48,
      },
      // Act 3 (Scene 2): Junction Inspection (Computer Vision)
      {
        pos: new THREE.Vector3(26, 24, 38),
        target: new THREE.Vector3(0, 3, 0),
        fov: 46,
      },
      // Act 4 (Scene 3): Elegant Isometric Urban Perspective
      {
        pos: new THREE.Vector3(55, 115, 165),
        target: new THREE.Vector3(0, 16, 0),
        fov: 42,
      },
    ];

    let currentPos = actTargets[0].pos.clone();
    let currentTarget = actTargets[0].target.clone();

    // 12. Animation Loop & Performance Management
    const prefersReducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let clock = new THREE.Clock();
    let ringScale = 1;

    const animate = () => {
      if (isDisposed) return;
      animId = requestAnimationFrame(animate);

      const delta = clock.getDelta();
      const time = clock.getElapsedTime();
      const activeScene = Math.max(0, Math.min(3, sceneRef.current));
      const targetConfig = actTargets[activeScene] || actTargets[0];

      // Smooth camera lerp (or instant if prefers-reduced-motion)
      const lerpSpeed = prefersReducedMotion ? 1 : 0.055;
      currentPos.lerp(targetConfig.pos, lerpSpeed);
      currentTarget.lerp(targetConfig.target, lerpSpeed);

      threeCamera.position.copy(currentPos);
      threeCamera.lookAt(currentTarget);

      // Act Transitions & Material Modulation
      if (activeScene === 0) {
        // Act 1: Living Daylight City
        rainMat.opacity = THREE.MathUtils.lerp(rainMat.opacity, 0, 0.08);
        waterSegMat.opacity = THREE.MathUtils.lerp(waterSegMat.opacity, 0, 0.08);
        ringMat.opacity = THREE.MathUtils.lerp(ringMat.opacity, 0, 0.08);
        threeScene.background = new THREE.Color("#EAF3FB");
        if (threeScene.fog) (threeScene.fog as THREE.Fog).color.set("#DDEAF6");
        warningTubeMat.color.set("#168BD2");
      } else if (activeScene === 1) {
        // Act 2: Daylight Rain & Hazard Warnings
        rainMat.opacity = THREE.MathUtils.lerp(rainMat.opacity, 0.75, 0.06);
        waterSegMat.opacity = THREE.MathUtils.lerp(waterSegMat.opacity, 0, 0.08);
        ringMat.opacity = THREE.MathUtils.lerp(ringMat.opacity, 0, 0.08);
        threeScene.background = new THREE.Color("#DEEAF4");
        if (threeScene.fog) (threeScene.fog as THREE.Fog).color.set("#CFE0EE");
        // Warning route turns Amber (#E8A13B)
        warningTubeMat.color.set("#E8A13B");
      } else if (activeScene === 2) {
        // Act 3: Computer Vision & Water Segmentation
        rainMat.opacity = THREE.MathUtils.lerp(rainMat.opacity, 0.25, 0.06);
        waterSegMat.opacity = THREE.MathUtils.lerp(waterSegMat.opacity, 0.75, 0.08);
        ringMat.opacity = THREE.MathUtils.lerp(ringMat.opacity, 0.85, 0.08);
        threeScene.background = new THREE.Color("#E4EFF8");
        if (threeScene.fog) (threeScene.fog as THREE.Fog).color.set("#D6E6F4");
        warningTubeMat.color.set("#E8A13B");

        // Animate radar ring pulse
        ringScale += delta * 18;
        if (ringScale > 28) ringScale = 2;
        ringMesh.scale.set(ringScale, ringScale, 1);
        ringMat.opacity = (1 - ringScale / 28) * 0.9;
      } else {
        // Act 4: Abstract Topological Navigation
        rainMat.opacity = THREE.MathUtils.lerp(rainMat.opacity, 0, 0.08);
        waterSegMat.opacity = THREE.MathUtils.lerp(waterSegMat.opacity, 0, 0.08);
        ringMat.opacity = THREE.MathUtils.lerp(ringMat.opacity, 0, 0.08);
        threeScene.background = new THREE.Color("#E8F2FA");
        if (threeScene.fog) (threeScene.fog as THREE.Fog).color.set("#DBE9F6");
        warningTubeMat.color.set("#18B6AD");
      }

      // Animate Vehicles along routes
      if (!prefersReducedMotion) {
        const vPos = vehicleGeo.attributes.position.array as Float32Array;
        for (let i = 0; i < vehicleCount; i++) {
          const t = (time * vehicleSpeeds[i] * 18 + i / vehicleCount) % 1;
          const curve = vehicleCurves[i] ? primaryRouteCurve : warningRouteCurve;
          const pt = curve.getPointAt(t);
          vPos[i * 3] = pt.x;
          vPos[i * 3 + 1] = pt.y + 0.35;
          vPos[i * 3 + 2] = pt.z;
        }
        vehicleGeo.attributes.position.needsUpdate = true;
      }

      // Animate Rain Particles
      if (rainMat.opacity > 0.02 && !prefersReducedMotion) {
        const rPos = rainGeo.attributes.position.array as Float32Array;
        for (let i = 0; i < rainCount; i++) {
          rPos[i * 3 + 1] -= delta * 75; // Fall velocity
          if (rPos[i * 3 + 1] < 0) {
            rPos[i * 3 + 1] = 120 + Math.random() * 20;
          }
        }
        rainGeo.attributes.position.needsUpdate = true;
      }

      // Gentle building sway / subtle breathing in camera
      if (!prefersReducedMotion) {
        threeScene.rotation.y = Math.sin(time * 0.12) * 0.02;
      }

      renderer.render(threeScene, threeCamera);
    };

    animId = requestAnimationFrame(animate);
    setReady(true);
    setFailed(false);

    const onVisibilityChange = () => {
      if (document.hidden) {
        cancelAnimationFrame(animId);
      } else {
        clock.start();
        animId = requestAnimationFrame(animate);
      }
    };
    document.addEventListener("visibilitychange", onVisibilityChange);

    // 13. Responsive Resize Handler
    const resizeObserver = new ResizeObserver(() => {
      if (!container || !renderer) return;
      const w = container.clientWidth;
      const h = Math.max(container.clientHeight, 1);
      threeCamera.aspect = w / h;
      threeCamera.updateProjectionMatrix();
      renderer.setSize(w, h);
    });
    resizeObserver.observe(container);

    // 14. Cleanup & Resource Disposal
    return () => {
      isDisposed = true;
      cancelAnimationFrame(animId);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      resizeObserver.disconnect();

      // Dispose Geometries
      boxGeo.dispose();
      groundGeo.dispose();
      riverGeo.dispose();
      primaryTubeGeo.dispose();
      warningTubeGeo.dispose();
      crossRoadGeo.dispose();
      dashLineGeo.dispose();
      vehicleGeo.dispose();
      rainGeo.dispose();
      waterSegGeo.dispose();
      beaconGeo.dispose();
      ringGeo.dispose();

      // Dispose Materials
      matConcrete.dispose();
      matPearl.dispose();
      matGlass.dispose();
      groundMat.dispose();
      riverMat.dispose();
      primaryTubeMat.dispose();
      warningTubeMat.dispose();
      crossRoadMat.dispose();
      dashLineMat.dispose();
      vehicleMat.dispose();
      rainMat.dispose();
      waterSegMat.dispose();
      beaconMat.dispose();
      ringMat.dispose();
      bboxMatCar.dispose();
      bboxMatBike.dispose();

      // Dispose Renderer
      if (renderer) {
        renderer.dispose();
        if (renderer.domElement && renderer.domElement.parentNode) {
          renderer.domElement.parentNode.removeChild(renderer.domElement);
        }
      }
    };
  }, []);

  return (
    <div className="observatory-map" data-map-ready={ready} data-map-failed={failed}>
      <div
        ref={containerRef}
        className="observatory-map-canvas w-full h-full relative"
        aria-label="Thành phố 3D TP.HCM ban ngày - SafePath AI"
      />
      {failed && (
        <span className="map-unavailable" role="status">
          Không tải được không gian 3D. Dữ liệu camera và bản tin giao thông vẫn hoạt động bình thường.
        </span>
      )}
    </div>
  );
}
