// CloudFront Function, viewer-response, runtime cloudfront-js-2.0 (strict mode; kept to ES5 style on purpose).
// Source: infra/functions/headers.template.js. infra/render.py fills CONFIG with the site's one Content-Security-Policy string
// (the dashboard's inline-script hashes plus the union of the agents' external hosts, see infra/msp_render/functions.py).
// It is set here and not by the response-headers policy because that policy may carry at most 1,783 characters of CSP
// and the hashes alone take about 60 characters each.
// Only HTML gets a policy, and every HTML page gets the same one: every agent's screens run on the dashboard's pages.
// (CloudFront does not run viewer-response functions for 4xx/5xx origin answers, which carry no HTML here.)
var CSP = __CONFIG__;

function handler(event) {
  var response = event.response;
  var type = response.headers['content-type'];
  if (!type || type.value.toLowerCase().indexOf('text/html') !== 0) {
    return response;
  }
  response.headers['content-security-policy'] = { value: CSP };
  return response;
}
