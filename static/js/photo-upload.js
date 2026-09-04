/* Direct-to-R2 photo upload for the teacher's day screen.
 *
 * Three steps, and the order matters:
 *   1. POST to `upload_url` — Django writes a PENDING MediaAsset row and hands back a
 *      presigned PUT scoped to that one key and content type.
 *   2. PUT the bytes straight to Cloudflare. They never pass through Django: a 12 MP
 *      photo through the VPS would hold a gunicorn worker for the length of a 4G
 *      upload, and there are three workers.
 *   3. POST to `confirm` so the row can go PENDING -> STORED.
 *
 * If step 3 never happens the row stays PENDING and the nightly reconciliation
 * settles it against the bucket. That is why the row is written first.
 *
 * Progressive enhancement: with no JavaScript the file input simply does nothing
 * visible, which is the honest outcome — there is no non-JS path to a presigned PUT,
 * and every other control on this screen is a real form that works without it.
 */
(function () {
  "use strict";

  var MAX_EDGE = 1600; // Plenty for a phone feed, and roughly a tenth of the bytes.
  var JPEG_QUALITY = 0.82;

  function csrfToken(form) {
    var field = form.querySelector('input[name="csrfmiddlewaretoken"]');
    return field ? field.value : "";
  }

  /* Downscale in the browser before uploading.
   *
   * The teacher is on mobile data and a modern phone photo is 4-12 MB; resized it is
   * a few hundred KB. Anything the browser cannot decode — HEIC, most notably, which
   * iPhones still produce — falls through and uploads as it came, because a failed
   * decode must not become a failed upload.
   */
  function shrink(file) {
    if (!window.createImageBitmap || !file.type.startsWith("image/")) {
      return Promise.resolve({ blob: file, type: file.type, width: null, height: null });
    }
    return createImageBitmap(file)
      .then(function (bitmap) {
        var scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
        var w = Math.round(bitmap.width * scale);
        var h = Math.round(bitmap.height * scale);
        var canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        canvas.getContext("2d").drawImage(bitmap, 0, 0, w, h);
        bitmap.close();
        return new Promise(function (resolve) {
          canvas.toBlob(
            function (blob) {
              // A canvas that refuses to encode gives null; send the original.
              if (!blob) {
                resolve({ blob: file, type: file.type, width: null, height: null });
              } else {
                resolve({ blob: blob, type: "image/jpeg", width: w, height: h });
              }
            },
            "image/jpeg",
            JPEG_QUALITY
          );
        });
      })
      .catch(function () {
        // HEIC and friends land here. Upload untouched and let the server cope.
        return { blob: file, type: file.type, width: null, height: null };
      });
  }

  function uploadOne(file, config, token) {
    return shrink(file).then(function (shrunk) {
      var ask = new FormData();
      ask.append("csrfmiddlewaretoken", token);
      ask.append("filename", file.name);
      // Drawing on a canvas discards EXIF orientation by applying it, so what we
      // declare here is what we are actually sending, not what the phone produced.
      ask.append("content_type", shrunk.type);

      return fetch(config.urlEndpoint, { method: "POST", body: ask })
        .then(function (response) {
          return response.json().then(function (data) {
            if (!response.ok) throw new Error(data.error || "Could not start the upload.");
            return data;
          });
        })
        .then(function (grant) {
          return fetch(grant.url, {
            method: "PUT",
            body: shrunk.blob,
            headers: { "Content-Type": shrunk.type },
          }).then(function (put) {
            if (!put.ok) throw new Error("The photo service rejected the upload.");
            var done = new FormData();
            done.append("csrfmiddlewaretoken", token);
            done.append("byte_size", shrunk.blob.size);
            if (shrunk.width) done.append("width", shrunk.width);
            if (shrunk.height) done.append("height", shrunk.height);
            return fetch(grant.confirm, { method: "POST", body: done });
          });
        });
    });
  }

  function wire(root) {
    var input = root.querySelector("[data-photo-input]");
    var status = root.querySelector("[data-photo-status]");
    if (!input) return;

    var config = { urlEndpoint: root.dataset.uploadUrl };
    var token = csrfToken(root);

    input.addEventListener("change", function () {
      var files = Array.prototype.slice.call(input.files || []);
      if (!files.length) return;

      var done = 0;
      var failed = 0;
      status.textContent = "Uploading " + files.length + "…";

      // One at a time. School wifi with six parallel PUTs is slower than six in a
      // row, and a teacher watching a counter climb knows it is working.
      files
        .reduce(function (chain, file) {
          return chain.then(function () {
            return uploadOne(file, config, token)
              .then(function () {
                done += 1;
              })
              .catch(function (error) {
                failed += 1;
                status.textContent = error.message;
              })
              .then(function () {
                if (!failed) status.textContent = "Uploaded " + done + " of " + files.length + "…";
              });
          });
        }, Promise.resolve())
        .then(function () {
          if (done) {
            status.textContent = "Uploaded " + done + ". Reloading…";
            window.location.reload();
          }
        });
    });
  }

  document.querySelectorAll("[data-photo-uploader]").forEach(wire);
})();
