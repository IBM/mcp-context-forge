import common from "./common.json";
import navigation from "./navigation.json";
import auth from "./auth.json";
import dashboard from "./dashboard.json";
import restApi from "./restApi.json";
import grpc from "./grpc.json";

export default {
  ...common,
  ...navigation,
  ...auth,
  ...dashboard,
  ...restApi,
  ...grpc,
};
