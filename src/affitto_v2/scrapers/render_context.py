from __future__ import annotations

from typing import Protocol

from .browser.session_policy import HardwareMimetics


def build_render_context_init_script(hardware: HardwareMimetics) -> str:
    script = """
(() => {
  if (globalThis.__affittoRenderContextPatched) {
    return;
  }
  Object.defineProperty(globalThis, '__affittoRenderContextPatched', {
    configurable: false,
    enumerable: false,
    writable: false,
    value: true,
  });

  const defineNavigatorValue = (propertyName, value) => {
    const target = Navigator.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(target, propertyName);
    if (descriptor && descriptor.configurable === false) {
      return;
    }
    Object.defineProperty(target, propertyName, {
      configurable: true,
      enumerable: descriptor ? descriptor.enumerable : true,
      get: () => value,
    });
  };

  defineNavigatorValue('hardwareConcurrency', __HARDWARE_CONCURRENCY__);
  defineNavigatorValue('userAgent', __USER_AGENT__);

  const vendor = __WEBGL_VENDOR__;
  const renderer = __WEBGL_RENDERER__;
  const maskedVendor = 0x1F00;
  const maskedRenderer = 0x1F01;
  const unmaskedVendor = 0x9245;
  const unmaskedRenderer = 0x9246;

  const patchWebGLGetParameter = (constructorRef) => {
    if (!constructorRef || !constructorRef.prototype || constructorRef.prototype.__affittoGetParameterPatched) {
      return;
    }
    const originalGetParameter = constructorRef.prototype.getParameter;
    Object.defineProperty(constructorRef.prototype, '__affittoGetParameterPatched', {
      configurable: false,
      enumerable: false,
      writable: false,
      value: true,
    });
    Object.defineProperty(constructorRef.prototype, 'getParameter', {
      configurable: true,
      writable: true,
      value: function(parameter) {
        if (parameter === maskedVendor || parameter === unmaskedVendor) {
          return vendor;
        }
        if (parameter === maskedRenderer || parameter === unmaskedRenderer) {
          return renderer;
        }
        return originalGetParameter.apply(this, arguments);
      },
    });
  };

  patchWebGLGetParameter(globalThis.WebGLRenderingContext);
  patchWebGLGetParameter(globalThis.WebGL2RenderingContext);

  if (!globalThis.HTMLCanvasElement || !HTMLCanvasElement.prototype) {
    return;
  }

  const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
  if (typeof originalToDataURL !== 'function' || HTMLCanvasElement.prototype.__affittoToDataURLPatched) {
    return;
  }

  Object.defineProperty(HTMLCanvasElement.prototype, '__affittoToDataURLPatched', {
    configurable: false,
    enumerable: false,
    writable: false,
    value: true,
  });

  const createNoisyCanvas = (sourceCanvas) => {
    const width = sourceCanvas.width >>> 0;
    const height = sourceCanvas.height >>> 0;
    if (!width || !height) {
      return null;
    }

    const clone = document.createElement('canvas');
    clone.width = width;
    clone.height = height;
    const context = clone.getContext('2d');
    if (!context) {
      return null;
    }

    context.drawImage(sourceCanvas, 0, 0);

    try {
      const imageData = context.getImageData(0, 0, width, height);
      const { data } = imageData;
      const xStride = Math.max(1, Math.floor(width / 8));
      const yStride = Math.max(1, Math.floor(height / 8));

      for (let y = 0; y < height; y += yStride) {
        for (let x = 0; x < width; x += xStride) {
          const index = ((y * width) + x) * 4;
          data[index] = (data[index] + 1) & 0xFF;
          data[index + 1] = (data[index + 1] + 2) & 0xFF;
          data[index + 2] = (data[index + 2] + 3) & 0xFF;
        }
      }

      context.putImageData(imageData, 0, 0);
    } catch (error) {
      return clone;
    }

    return clone;
  };

  Object.defineProperty(HTMLCanvasElement.prototype, 'toDataURL', {
    configurable: true,
    writable: true,
    value: function(...args) {
      const noisyCanvas = createNoisyCanvas(this);
      if (!noisyCanvas) {
        return originalToDataURL.apply(this, args);
      }
      return originalToDataURL.apply(noisyCanvas, args);
    },
  });
})();
""".strip()
    return (
        script.replace("__HARDWARE_CONCURRENCY__", str(hardware.hardware_concurrency))
        .replace("__USER_AGENT__", repr(hardware.user_agent))
        .replace("__WEBGL_VENDOR__", repr(hardware.webgl_vendor))
        .replace("__WEBGL_RENDERER__", repr(hardware.webgl_renderer))
    )


GLOBAL_RENDER_CONTEXT_INIT_SCRIPT = build_render_context_init_script(
    HardwareMimetics(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0"
        ),
        device_memory=16,
        hardware_concurrency=8,
        webgl_vendor="Intel Inc.",
        webgl_renderer="Intel(R) Iris(TM) Graphics Xe",
    )
)


class SupportsInitScript(Protocol):
    async def add_init_script(self, *, script: str | None = None, path: str | None = None) -> None: ...


async def install_render_context_init_script(
    context: SupportsInitScript,
    *,
    hardware: HardwareMimetics | None = None,
    logger=None,
) -> None:
    selected_hardware = hardware or HardwareMimetics(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0"
        ),
        device_memory=16,
        hardware_concurrency=8,
        webgl_vendor="Intel Inc.",
        webgl_renderer="Intel(R) Iris(TM) Graphics Xe",
    )
    await context.add_init_script(script=build_render_context_init_script(selected_hardware))
    if logger is not None:
        logger.info(
            "Installed render context init script. navigator_user_agent=%s navigator_hardware_concurrency=%s webgl_vendor=%s webgl_renderer=%s canvas_noise=%s",
            selected_hardware.user_agent,
            selected_hardware.hardware_concurrency,
            selected_hardware.webgl_vendor,
            selected_hardware.webgl_renderer,
            selected_hardware.canvas_noise_mode,
        )


__all__ = [
    "build_render_context_init_script",
    "GLOBAL_RENDER_CONTEXT_INIT_SCRIPT",
    "install_render_context_init_script",
]
