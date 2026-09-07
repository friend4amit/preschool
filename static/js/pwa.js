/* Register the service worker, and offer to install — on the portal only.
 *
 * Loaded from layouts/parent.html rather than base.html on purpose. The public site is
 * for people deciding whether to enrol; an install prompt there is an app nobody has
 * a login for. The worker's scope is /portal/ for the same reason.
 *
 * Both halves are optional enhancements. With this file blocked or JavaScript off the
 * portal is exactly the site it was before — no worker, no prompt, every page still a
 * real page.
 */
(function () {
  "use strict";

  var root = document.currentScript && document.currentScript.dataset;
  var workerUrl = (root && root.worker) || "/sw.js";
  var scope = (root && root.scope) || "/portal/";

  if ("serviceWorker" in navigator) {
    // After load, not during: registering competes with the first paint for the
    // network on exactly the connections this is meant to help.
    window.addEventListener("load", function () {
      navigator.serviceWorker.register(workerUrl, { scope: scope }).catch(function () {
        /* No worker is a working site, so a failure here is not worth a message. */
      });
    });
  }

  /* The install nudge.
   *
   * Chrome fires `beforeinstallprompt` when it decides the app is installable and
   * lets us defer it; there is no equivalent on iOS, where installing is Share ->
   * Add to Home Screen and cannot be triggered by a page. So this button appears
   * where the browser offers it and stays hidden where it does not, rather than
   * being a permanent piece of furniture that does nothing on half of phones.
   */
  var deferred = null;
  // Two elements: the bar to reveal, and the button inside it that acts. They are
  // separate because the bar is the layout and the button is the control — and the
  // bar is the thing `hidden` toggles.
  var bar = document.querySelector("[data-install-app]");
  var button = bar && bar.querySelector("[data-install-go]");
  if (!bar || !button) return;

  function alreadyAsked() {
    try {
      return Boolean(localStorage.getItem("aaroham-install-asked"));
    } catch (error) {
      // Private mode. Asking again next session is a small enough cost.
      return false;
    }
  }

  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault();
    deferred = event;
    // Checked here rather than at load: the button is hidden until the browser says
    // the app is installable, so "already asked" only has to suppress this moment.
    if (!alreadyAsked()) bar.hidden = false;
  });

  button.addEventListener("click", function () {
    if (!deferred) return;
    deferred.prompt();
    deferred.userChoice.then(function () {
      // One offer. A parent who declined does not want to be asked on every page.
      deferred = null;
      bar.hidden = true;
      try {
        localStorage.setItem("aaroham-install-asked", "1");
      } catch (error) {
        /* Storage unavailable; the offer simply returns next session. */
      }
    });
  });

  // Already installed: the browser stops firing the event, but say so anyway.
  window.addEventListener("appinstalled", function () {
    bar.hidden = true;
  });
})();
