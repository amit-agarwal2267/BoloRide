class DomainValidationError(ValueError):
    """A provider-independent domain value is invalid."""


class InvalidRideTransitionError(DomainValidationError):
    """A ride status transition is not allowed."""


class LocationProviderError(DomainValidationError):
    """A configured location provider failed to return usable results."""


class LocationProviderTimeoutError(LocationProviderError):
    """A location provider exceeded its request timeout."""


class LocationNotFoundError(LocationProviderError):
    """A location provider returned no candidates."""


class LocationConfigurationError(LocationProviderError):
    """The selected location provider is not configured or implemented."""


class RouteProviderError(DomainValidationError):
    """Configured routing providers failed to return authoritative route facts."""


class RouteSanityError(DomainValidationError):
    """Provider route facts contradict trusted endpoint geography."""
