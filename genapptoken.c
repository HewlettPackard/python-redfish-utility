// main.c
#include <stdio.h>
#include <string.h>
#include <dlfcn.h>
#include <stdbool.h>

int main(int argc, char *argv[]) {


    char* HOSTAPP_ID = "self_register";
    char* HOSTAPP_NAME = "self_register";
    char* SALT = "self_register";

    if (argc != 3) {
        printf("Usage: %s <username> <password>\n", argv[0]);
        return 1;
    }

    char *username = argv[1];
    char *password = argv[2];


    // Open the shared library
    void* handle = dlopen("/usr/lib64/ilorest_chif.so", RTLD_LAZY);
    if (!handle) {
        fprintf(stderr, "Error loading library: %s\n", dlerror());
        return 1;
    }
    // Clear any existing errors
    dlerror();
    // Get a pointer to the GenerateAppToken function
    int (*genapptoken_function)(char*, char*, char*, char*, char*);
    *(void**)(&genapptoken_function) = dlsym(handle, "GenerateAppToken");
    char* error = dlerror();
    if (error) {
        fprintf(stderr, "Error locating GenerateAppToken: %s\n", error);
        dlclose(handle);
        return 1;
    }
    // Get a pointer to the VnicExists function
    int (*vnicexists_function)();
    *(void**)(&vnicexists_function) = dlsym(handle, "ReadyToUse");
    error = dlerror();
    if (error) {
        fprintf(stderr, "Error locating VnicExists: %s\n", error);
        dlclose(handle);
        return 1;
    }
    // Get a pointer to the AppIdExistsinTPM function
    int (*appidexists_function)(char*, bool*);
    *(void**)(&appidexists_function) = dlsym(handle, "AppIdExistsinTPM");
    error = dlerror();
    if (error) {
        fprintf(stderr, "Error locating AppIdExistsinTPM: %s\n", error);
        dlclose(handle);
        return 1;
    }
    bool (*enabledebug_function)(const char*);
    *(void**)(&enabledebug_function) = dlsym(handle, "enabledebugoutput");
    const char *logdir= "/root/";
    bool b = enabledebug_function(logdir);

    // Check if VNIC exists, 0 means exists
    if (!vnicexists_function()) {
        bool appid_exists = false;
        bool result = appidexists_function(HOSTAPP_ID, &appid_exists);
        if (result) {
            fprintf(stderr, "Error calling AppIdExistsinTPM.\n");
            dlclose(handle);
            return 1;
        }
        if (!appid_exists) {
            // Call GenerateAppToken
            int result = genapptoken_function(HOSTAPP_ID, HOSTAPP_NAME, SALT, username, password);
            if (!result) {
                fprintf(stderr, "Successfully created the application account.\nApplication installed successfully.\n");
                return 0;
            } else {
                return 1;
            }
        } else {
            fprintf(stderr, "Skipping the application account creation as it already exists.\nApplication installed successfully.\n");
        }
    }
    // Close the library
    dlclose(handle);
    return 0;
}
