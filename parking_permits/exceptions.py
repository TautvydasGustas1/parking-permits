class ParkingPermitBaseException(Exception):
    pass


class PermitLimitExceeded(ParkingPermitBaseException):
    pass


class DuplicatePermit(ParkingPermitBaseException):
    pass


class PriceError(ParkingPermitBaseException):
    pass


class InvalidUserAddress(ParkingPermitBaseException):
    pass


class InvalidContractType(ParkingPermitBaseException):
    pass


class RefundError(ParkingPermitBaseException):
    pass


class NonDraftPermitUpdateError(ParkingPermitBaseException):
    pass


class PermitCanNotBeDelete(ParkingPermitBaseException):
    pass


class PermitCanNotBeEnded(ParkingPermitBaseException):
    pass


class ObjectNotFound(ParkingPermitBaseException):
    pass


class CreateTalpaProductError(ParkingPermitBaseException):
    pass


class OrderCreationFailed(ParkingPermitBaseException):
    pass


class UpdatePermitError(ParkingPermitBaseException):
    pass


class CreatePermitError(ParkingPermitBaseException):
    pass


class ProductCatalogError(ParkingPermitBaseException):
    pass


class ParkingZoneError(ParkingPermitBaseException):
    pass


class ParkkihubiPermitError(ParkingPermitBaseException):
    pass


class AddressError(ParkingPermitBaseException):
    pass


class TraficomFetchVehicleError(ParkingPermitBaseException):
    pass


class DVVIntegrationError(ParkingPermitBaseException):
    pass


class SearchError(ParkingPermitBaseException):
    pass


class LocationDoesNotExist(ParkingPermitBaseException):
    pass
