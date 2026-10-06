"""Memory inference stays on literal loopback, without proxies or redirects."""
import urllib.error
import urllib.request

from aries.intelligence.providers import loopback_url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise urllib.error.HTTPError(req.full_url,code,'Local inference redirect refused',headers,fp)


def open_local(request,*,timeout):
    url=request.full_url if isinstance(request,urllib.request.Request) else request
    loopback_url(url)
    # A new private opener also ignores globally installed urllib handlers.
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),_NoRedirect())
    return opener.open(request,timeout=timeout)
