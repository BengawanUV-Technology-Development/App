import { useEffect, useRef } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

const MODEL_HEADING_OFFSET_DEG = 0;
const ACCENT_NAME_PATTERN = /(accent|nose|tip|tail|prop|motor|stripe|logo)/i;

function toRadians(value) {
  return THREE.MathUtils.degToRad(Number(value || 0));
}

function AircraftModel3D({
  headingDeg = 0,
  rollDeg = 0,
  pitchDeg = 0,
  modelColor = "#e2e8f0",
  accentColor = "#ef4444",
}) {
  const mountRef = useRef(null);
  const attitudeRef = useRef({ headingDeg, rollDeg, pitchDeg });

  useEffect(() => {
    attitudeRef.current = { headingDeg, rollDeg, pitchDeg };
  }, [headingDeg, rollDeg, pitchDeg]);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;

    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.setClearColor(0x000000, 0);
    mount.appendChild(renderer.domElement);
    mount.classList.add("is-model-loading");

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 100);
    camera.position.set(0, 2.2, 5.8);
    camera.lookAt(0, 0, 0);

    const root = new THREE.Group();
    scene.add(root);

    const ambient = new THREE.HemisphereLight(0xffffff, 0x1e293b, 2.4);
    scene.add(ambient);

    const key = new THREE.DirectionalLight(0xffffff, 2.6);
    key.position.set(2.5, 4, 5);
    scene.add(key);

    const rim = new THREE.DirectionalLight(0x93c5fd, 1.5);
    rim.position.set(-4, 2, -2);
    scene.add(rim);

    let loadedModel = null;
    let modelGroup = null;
    let disposed = false;

    const loader = new GLTFLoader();
    loader.load(
      "/img/wahana.glb",
      (gltf) => {
        if (disposed) return;
        loadedModel = gltf.scene;

        const box = new THREE.Box3().setFromObject(loadedModel);
        const center = box.getCenter(new THREE.Vector3());
        const size = box.getSize(new THREE.Vector3());
        const maxAxis = Math.max(size.x, size.y, size.z) || 1;
        const scale = 3.8 / maxAxis;

        modelGroup = new THREE.Group();
        loadedModel.position.copy(center).multiplyScalar(-1);
        loadedModel.rotation.set(0, 0, 0);
        loadedModel.traverse((node) => {
          if (node.isMesh) {
            node.castShadow = false;
            node.receiveShadow = false;
            const sourceMaterials = Array.isArray(node.material) ? node.material : [node.material];
            const materials = sourceMaterials.map((sourceMaterial) => {
              const material = sourceMaterial.clone();
              const identity = `${node.name} ${material.name}`;
              material.color?.set(ACCENT_NAME_PATTERN.test(identity) ? accentColor : modelColor);
              material.roughness = Math.max(Number(material.roughness ?? 0.6), 0.35);
              material.needsUpdate = true;
              return material;
            });
            node.material = Array.isArray(node.material) ? materials : materials[0];
          }
        });

        modelGroup.scale.setScalar(scale);
        modelGroup.add(loadedModel);
        root.add(modelGroup);
        mount.classList.remove("is-model-loading", "is-model-error");
        mount.classList.add("is-model-loaded");
      },
      undefined,
      (error) => {
        console.warn("[aircraft-model] failed to load /img/wahana.glb", error);
        mount.classList.remove("is-model-loading");
        mount.classList.add("is-model-error");
      },
    );

    const resize = () => {
      const width = mount.clientWidth || 120;
      const height = mount.clientHeight || 120;
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };

    const observer = new ResizeObserver(resize);
    observer.observe(mount);
    resize();

    let frameId = 0;
    const render = () => {
      const attitude = attitudeRef.current;
      root.rotation.x = toRadians(attitude.pitchDeg * 0.55);
      root.rotation.y = toRadians((attitude.headingDeg || 0) + MODEL_HEADING_OFFSET_DEG);
      root.rotation.z = toRadians(-attitude.rollDeg * 0.65);
      renderer.render(scene, camera);
      frameId = requestAnimationFrame(render);
    };
    render();

    return () => {
      disposed = true;
      cancelAnimationFrame(frameId);
      observer.disconnect();
      if (loadedModel) {
        loadedModel.traverse((node) => {
          if (node.geometry) node.geometry.dispose();
          if (node.material) {
            const materials = Array.isArray(node.material) ? node.material : [node.material];
            materials.forEach((material) => material.dispose());
          }
        });
      }
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [accentColor, modelColor]);

  return (
    <div className="aircraft-model-3d" ref={mountRef}>
      <div className="aircraft-model-fallback">
        <span className="fallback-wing fallback-wing-left" />
        <span className="fallback-wing fallback-wing-right" />
        <span className="fallback-body" />
      </div>
    </div>
  );
}

export default AircraftModel3D;
