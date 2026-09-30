export function preventAuthCaching(headers: Headers) {
  headers.set("Cache-Control", "private, no-store, max-age=0");
  headers.set("Pragma", "no-cache");
  headers.set("Expires", "0");
}

export function privateResponse(response: Response): Response {
  preventAuthCaching(response.headers);
  return response;
}

export function authRedirect(request: Request, path: string): Response {
  // An explicit 303 also turns form submissions into a GET at the destination.
  return privateResponse(new Response(null, { status: 303, headers: { Location: new URL(path, request.url).href } }));
}
